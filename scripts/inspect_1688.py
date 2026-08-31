"""Print non-sensitive DOM structure for adapting the 1688 collector."""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from app.collectors.alibaba1688 import CHROME_PATHS, search_url
from app.config import BROWSER_PROFILE


async def main():
    executable = next((str(path) for path in CHROME_PATHS if Path(path).exists()), None)
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(BROWSER_PROFILE), executable_path=executable, headless=False,
            viewport={"width": 1440, "height": 960},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(search_url("植物染发剂"), wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(5000)
        info = await page.evaluate(
            """() => ({
                title: document.title,
                charset: document.characterSet,
                cards: [...document.querySelectorAll('[data-offer-id], [data-offerid]')].slice(0,10).map(e => ({
                  tag:e.tagName, cls:e.className, offer:e.getAttribute('data-offer-id')||e.getAttribute('data-offerid'), text:(e.innerText||'').slice(0,300)
                })),
                links: [...document.querySelectorAll('a')].slice(0,120).map(a => ({href:a.href, text:(a.innerText||a.title||'').trim().slice(0,120)})).filter(x => x.href)
            })"""
        )
        print(json.dumps(info, ensure_ascii=False, indent=2))
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
