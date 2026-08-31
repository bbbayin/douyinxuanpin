import asyncio
import random
import re
from pathlib import Path
from urllib.parse import parse_qs, quote_from_bytes, urlparse

from playwright.async_api import async_playwright

from ..config import BROWSER_PROFILE


SEARCH_URL = "https://s.1688.com/selloffer/offer_search.htm?keywords={}"
CHROME_PATHS = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
]


def parse_number(text: str) -> int | None:
    text = text.strip().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([万千]?)", text)
    if not match:
        return None
    value = float(match.group(1))
    multiplier = {"万": 10000, "千": 1000}.get(match.group(2), 1)
    return int(value * multiplier)


def parse_sales(text: str) -> tuple[int | None, str | None]:
    patterns = [
        r"(?:近30天|30天)?(?:成交|已售|付款)\s*([\d.,]+\s*[万千]?)\s*(?:笔|件|人)?",
        r"([\d.,]+\s*[万千]?)\s*(?:人付款|笔成交|件成交)",
        r"(?:全网)?\s*([\d.,]+\s*[万千]?)\s*\+?\s*件",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return parse_number(match.group(1)), match.group(0)
    return None, None


def parse_prices(text: str) -> tuple[float | None, float | None]:
    compact = re.sub(r"(?<=[\d¥￥.])\s+(?=[\d.])", "", text)
    match = re.search(r"[¥￥]\s*(\d+(?:\.\d+)?)(?:\s*[-~至]\s*(\d+(?:\.\d+)?))?", compact)
    if not match:
        return None, None
    return float(match.group(1)), float(match.group(2)) if match.group(2) else None


def offer_id(url: str) -> str | None:
    match = re.search(r"/offer/(\d+)\.html", url)
    if match:
        return match.group(1)
    query = parse_qs(urlparse(url).query)
    for key in ("offerId", "offer_id"):
        if query.get(key):
            return query[key][0]
    return None


def parse_repurchase_rate(text: str) -> float | None:
    match = re.search(r"回头率\s*(\d+(?:\.\d+)?)%", text)
    return float(match.group(1)) / 100 if match else None


def parse_shop_name(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    endings = ("有限公司", "经营部", "日用品厂", "化妆品厂", "贸易商行", "工作室")
    return next((line for line in reversed(lines) if line.endswith(endings)), None)


def is_login_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "login" in host or "passport" in host or "/member/signin" in url.lower()


def search_url(keyword: str, page_number: int = 1) -> str:
    # This legacy 1688 search endpoint interprets the query string as GBK.
    encoded = quote_from_bytes(keyword.encode("gbk"))
    url = SEARCH_URL.format(encoded)
    return url if page_number <= 1 else f"{url}&beginPage={page_number}"


class Alibaba1688Collector:
    def __init__(self, headless: bool = False):
        self.headless = headless

    def _browser_path(self) -> str | None:
        for path in CHROME_PATHS:
            if path.exists():
                return str(path)
        return None

    async def collect_page(self, page, keyword: str, limit: int = 40, page_number: int = 1) -> list[dict]:
        target_url = search_url(keyword, page_number)
        await page.goto(target_url, wait_until="domcontentloaded", timeout=90000)
        if is_login_url(page.url):
            if self.headless:
                raise RuntimeError("1688 登录态已失效，请先关闭自动采集并手动运行一次真实采集完成登录")
            try:
                await page.wait_for_url(lambda url: not is_login_url(url), timeout=180000)
            except Exception as exc:
                raise RuntimeError("等待 1688 登录超时，请重新运行采集并在3分钟内完成登录") from exc
            await page.goto(target_url, wait_until="domcontentloaded", timeout=90000)
        await self._wait_for_manual_verification(page)
        await page.wait_for_timeout(5000)
        for _ in range(3):
            await page.mouse.wheel(0, 1000)
            await page.wait_for_timeout(900)
        await self._wait_for_manual_verification(page)
        raw = await page.evaluate(
                r"""(limit) => {
                    const links = [...document.querySelectorAll('a[href*="offer/"], a[href*="detail.1688.com"], a[href*="detail.m.1688.com"][href*="offerId="]')];
                    const seen = new Set();
                    const rows = [];
                    for (const link of links) {
                      const href = link.href || '';
                      if (!(/offer\/\d+\.html/.test(href) || /[?&]offerId=\d+/.test(href)) || seen.has(href)) continue;
                      let card = link;
                      for (let i = 0; i < 7 && card.parentElement; i++) {
                        if ((card.innerText || '').length > 60 && card.querySelector('img')) break;
                        card = card.parentElement;
                      }
                      const text = (card.innerText || '').trim();
                      if (text.length < 15) continue;
                      const img = card.querySelector('img');
                      const ownLines = (link.innerText || '').split('\n').map(x => x.trim()).filter(Boolean);
                      const ownTitle = ownLines.find(x => x.length >= 8 && !/^[¥￥\d.万千+件]+$/.test(x));
                      rows.push({
                        url: href,
                        text,
                        title: link.getAttribute('title') || ownTitle || img?.alt || '',
                        image_url: img?.getAttribute('data-lazy-src') || img?.getAttribute('data-src') || img?.getAttribute('data-original') || img?.currentSrc || img?.src || '',
                      });
                      seen.add(href);
                      if (rows.length >= limit) break;
                    }
                    return rows;
                }""",
            limit,
        )
        title = await page.title()
        current_url = page.url
        if not raw:
            anchor_count = await page.locator("a").count()
            raise RuntimeError(f"1688 搜索页未识别到商品：title={title!r}, url={current_url!r}, links={anchor_count}")

        items = []
        seen_ids = set()
        for row in raw:
            ext_id = offer_id(row["url"])
            if not ext_id or ext_id in seen_ids:
                continue
            text = row.get("text", "")
            sales, raw_sales = parse_sales(text)
            price_min, price_max = parse_prices(text)
            title = re.sub(r"\s+", " ", row.get("title") or text.splitlines()[0]).strip()[:240]
            image_url = row.get("image_url") or None
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url
            if image_url and image_url.startswith("data:image"):
                image_url = None
            items.append({
                "external_id": ext_id,
                "title": title,
                "url": f"https://detail.1688.com/offer/{ext_id}.html",
                "image_url": image_url,
                "shop_name": parse_shop_name(text),
                "price_min": price_min,
                "price_max": price_max,
                "sales_count": sales,
                "repurchase_rate": parse_repurchase_rate(text),
                "raw_sales_text": raw_sales,
                "raw_text": text[:1000],
            })
            seen_ids.add(ext_id)
        return items

    async def _wait_for_manual_verification(self, page):
        title = await page.title()
        url_lower = page.url.lower()
        challenge = (
            is_login_url(page.url)
            or "captcha" in url_lower
            or "/punish" in url_lower
            or "验证码拦截" in title
            or await page.locator("iframe[src*='captcha'], .nc_iconfont.btn_slide, #nc_1_n1z").count() > 0
        )
        if not challenge:
            return
        if self.headless:
            raise RuntimeError("1688 要求安全验证：请关闭自动采集，手动运行一次采集并完成滑块验证")
        try:
            await page.bring_to_front()
            await page.wait_for_function(
                """() => !location.href.includes('/punish')
                    && !location.href.toLowerCase().includes('captcha')
                    && !document.title.includes('验证码拦截')
                    && !document.querySelector("iframe[src*='captcha'], .nc_iconfont.btn_slide, #nc_1_n1z")""",
                timeout=300000,
            )
        except Exception as exc:
            raise RuntimeError("等待人工完成 1688 滑块验证超时") from exc


async def collect_keywords(
    keywords: list[str],
    limit: int = 40,
    headless: bool = False,
    min_delay_seconds: int = 20,
    pages_per_keyword: int = 2,
):
    collector = Alibaba1688Collector(headless=headless)
    result = {}
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE),
            executable_path=collector._browser_path(),
            headless=headless,
            viewport={"width": 1440, "height": 960},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        for index, word in enumerate(keywords):
            if index:
                await asyncio.sleep(random.uniform(min_delay_seconds, min_delay_seconds + 12))
            items = []
            seen_ids = set()
            for page_number in range(1, max(1, min(pages_per_keyword, 3)) + 1):
                if page_number > 1:
                    await asyncio.sleep(random.uniform(min_delay_seconds, min_delay_seconds + 12))
                page_items = await collector.collect_page(page, word, limit=limit, page_number=page_number)
                for item in page_items:
                    if item["external_id"] not in seen_ids:
                        items.append(item)
                        seen_ids.add(item["external_id"])
            result[word] = items
        await context.close()
    return result
