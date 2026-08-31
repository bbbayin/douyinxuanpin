import asyncio
import hashlib
import random
import re
from pathlib import Path

from playwright.async_api import async_playwright

from ..config import DOUYIN_BROWSER_PROFILE


TARGET_URL = "https://fxg.jinritemai.com/ffa/bu/NewBusinessCenter"
CHROME_PATHS = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
]
BENEFIT_TERMS = ("搜索扶持", "上新扶持", "猜喜热卖权益", "新潮新品扶持", "猜喜冷启权益", "商品卡扶持", "甄选品扶持")
RECOMMENDATION_TERMS = ("全网热卖", "热度高", "成交增速快", "应季爆发", "高扶持甄选品", "中小商易爆单")


def parse_compact_number(value: str) -> int | None:
    match = re.search(r"([\d.]+)\s*([万千]?)", value.replace(",", ""))
    if not match:
        return None
    multiplier = {"万": 10000, "千": 1000}.get(match.group(2), 1)
    return int(float(match.group(1)) * multiplier)


def parse_volume_range(value: str) -> tuple[int | None, int | None]:
    if "小于" in value:
        number = parse_compact_number(value)
        return 0, number
    values = re.findall(r"[\d.]+\s*[万千]?", value.replace(",", ""))
    parsed = [parse_compact_number(item) for item in values]
    parsed = [item for item in parsed if item is not None]
    if not parsed:
        return None, None
    return (parsed[0], parsed[-1]) if len(parsed) > 1 else (parsed[0], parsed[0])


def parse_growth(value: str) -> float | None:
    match = re.search(r"(-?[\d.]+)%", value)
    return float(match.group(1)) / 100 if match else None


def parse_card_text(text: str) -> dict | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if "搜索次数" not in lines or "成交增速" not in lines:
        return None
    search_index = lines.index("搜索次数")
    growth_index = lines.index("成交增速")
    excluded = {"收藏", "+0", *BENEFIT_TERMS, *RECOMMENDATION_TERMS}
    title_candidates = [line for line in lines[:search_index] if line not in excluded and not line.startswith("选品建议")]
    if not title_candidates:
        return None
    title = title_candidates[-1]
    volume_text = lines[search_index + 1] if search_index + 1 < len(lines) else ""
    growth_text = lines[growth_index + 1] if growth_index + 1 < len(lines) else ""
    volume_min, volume_max = parse_volume_range(volume_text)
    benefits = [term for term in BENEFIT_TERMS if term in lines]
    recommendations = [term for term in RECOMMENDATION_TERMS if term in lines]
    return {
        "external_id": hashlib.sha256(title.encode("utf-8")).hexdigest()[:24],
        "title": title[:200],
        "search_volume_min": volume_min,
        "search_volume_max": volume_max,
        "search_volume_text": volume_text,
        "growth_rate": parse_growth(growth_text),
        "has_source": "找货源" in lines and "暂无货源" not in lines,
        "recommendation": "、".join(recommendations),
        "benefits": benefits,
        "raw_text": text[:1000],
    }


class DouyinOpportunityCollector:
    def __init__(self, headless: bool = False):
        self.headless = headless

    def _browser_path(self):
        return next((str(path) for path in CHROME_PATHS if path.exists()), None)

    async def _ensure_logged_in(self, page):
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(5000)
        if "NewBusinessCenter" in page.url and await page.get_by_text("商机中心", exact=True).count():
            return
        if self.headless:
            raise RuntimeError("抖店登录态已失效，请手动运行一次抖音采集并在打开的窗口中登录")
        await page.bring_to_front()
        try:
            await page.wait_for_url("**/ffa/**", timeout=300000)
        except Exception as exc:
            raise RuntimeError("等待抖店登录超时，请在5分钟内完成扫码登录") from exc
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(5000)

    async def collect(self, pages: int = 2) -> list[dict]:
        DOUYIN_BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(DOUYIN_BROWSER_PROFILE), executable_path=self._browser_path(),
                headless=self.headless, viewport={"width": 1440, "height": 960},
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await self._ensure_logged_in(page)
            items = []
            seen = set()
            for page_number in range(max(1, min(pages, 5))):
                await page.wait_for_timeout(4000)
                raw_cards = await page.evaluate(
                    """() => {
                      const labels = [...document.querySelectorAll('*')].filter(el =>
                        el.children.length === 0 && (el.textContent || '').trim() === '搜索次数');
                      const cards = [];
                      const seen = new Set();
                      for (const label of labels) {
                        let node = label.parentElement;
                        for (let i = 0; i < 9 && node; i++, node = node.parentElement) {
                          const text = (node.innerText || '').trim();
                          if (text.includes('成交增速') && text.includes('发相似品') && text.length < 1200) {
                            if (!seen.has(text)) { cards.push(text); seen.add(text); }
                            break;
                          }
                        }
                      }
                      return cards;
                    }"""
                )
                for raw in raw_cards:
                    item = parse_card_text(raw)
                    if item and item["external_id"] not in seen:
                        items.append(item)
                        seen.add(item["external_id"])
                if page_number + 1 >= pages:
                    break
                next_button = page.locator("li.ant-pagination-next:not(.ant-pagination-disabled) button, li[title='下一页'] button").first
                if not await next_button.count() or not await next_button.is_enabled():
                    break
                await asyncio.sleep(random.uniform(12, 20))
                await next_button.click()
            await context.close()
            if not items:
                raise RuntimeError("抖音商机中心未解析到机会词，请确认账号权限和页面是否正常")
            return items


async def collect_douyin_opportunities(pages: int = 2, headless: bool = False):
    return await DouyinOpportunityCollector(headless=headless).collect(pages)
