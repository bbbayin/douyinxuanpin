import asyncio
import logging
import threading

from playwright.async_api import async_playwright

from .collectors.douyin import CHROME_PATHS, PRODUCTS_URL, TARGET_URL
from .config import DOUYIN_BROWSER_PROFILE
from .douyin_session import PROFILE_LOCK


logger = logging.getLogger(__name__)


def _browser_path():
    return next((str(path) for path in CHROME_PATHS if path.exists()), None)


async def _wait_until_closed(context):
    while context.pages:
        await asyncio.sleep(1)


async def _show_failure(context, page, ready: threading.Event, outcome: dict, message: str):
    outcome.update({"accepted": False, "message": message})
    ready.set()
    await page.bring_to_front()
    await _wait_until_closed(context)


async def _open(action: str, title: str, source_page: int, ready: threading.Event, outcome: dict):
    DOUYIN_BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(DOUYIN_BROWSER_PROFILE), executable_path=_browser_path(),
            headless=False, viewport={"width": 1440, "height": 960},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        target = PRODUCTS_URL if action == "products" else TARGET_URL
        await page.goto(target, wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(5000)
        if "NewBusinessCenter" not in page.url:
            await _show_failure(
                context, page, ready, outcome,
                "抖店登录态已失效，登录窗口已保留；请登录后重新点击",
            )
            return

        if action == "source":
            target_page = max(1, min(source_page, 5))
            if target_page > 1:
                page_link = page.locator(
                    f"li.ant-pagination-item[title='{target_page}'] a, li[title='{target_page}'] a"
                ).first
                if not await page_link.count():
                    await _show_failure(
                        context, page, ready, outcome,
                        f"商机中心没有第{target_page}页，窗口已保留；请重新采集",
                    )
                    return
                await page_link.click()
                await page.wait_for_timeout(1800)

            title_locator = page.get_by_text(title, exact=True)
            if not await title_locator.count() or not await title_locator.last.is_visible():
                await _show_failure(
                    context, page, ready, outcome,
                    f"第{target_page}页没有找到“{title}”，窗口已保留；该商机可能已下榜，请重新采集",
                )
                return
            card = title_locator.last.locator(
                "xpath=ancestor::*[.//button[contains(normalize-space(.), '找货源')]][1]"
            )
            button = card.get_by_role("button", name="找货源")
            if not await button.count():
                await _show_failure(
                    context, page, ready, outcome,
                    f"“{title}”的找货源按钮已失效，窗口已保留；请重新采集",
                )
                return
            await button.click()
            source_panel = page.get_by_text("找官方源头好货", exact=False).last
            try:
                await source_panel.wait_for(state="visible", timeout=15000)
            except Exception:
                await _show_failure(
                    context, page, ready, outcome,
                    f"已找到“{title}”，但货源面板未打开；窗口已保留，请手动点击找货源",
                )
                return

        await page.bring_to_front()
        outcome.update({
            "accepted": True,
            "action": action,
            "message": "已打开抖音爆品总榜" if action == "products" else f"已打开“{title}”的官方货源",
        })
        ready.set()
        await _wait_until_closed(context)


def run_douyin_navigation(action: str, title: str, source_page: int = 1):
    if action not in {"products", "source"}:
        return {"accepted": False, "message": "不支持的抖音页面操作"}
    if not PROFILE_LOCK.acquire(blocking=False):
        return {"accepted": False, "message": "抖音窗口已经打开，请先在该窗口中查看或关闭后重试"}

    ready = threading.Event()
    outcome = {}

    def worker():
        try:
            asyncio.run(_open(action, title, source_page, ready, outcome))
        except Exception as exc:
            outcome.update({"accepted": False, "message": str(exc)})
            ready.set()
            logger.exception("打开抖音%s页面失败", action)
        finally:
            PROFILE_LOCK.release()

    threading.Thread(target=worker, name=f"douyin-open-{action}", daemon=True).start()
    if ready.wait(timeout=90):
        return outcome
    return {"accepted": False, "message": "打开抖音页面超时，请关闭Chrome窗口后重试"}
