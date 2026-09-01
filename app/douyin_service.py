import asyncio
import threading
from datetime import datetime, timezone

from .collectors.douyin import collect_douyin_opportunities
from .db import finish_run, start_run, upsert_douyin_opportunity
from .douyin_session import PROFILE_LOCK


def run_douyin_collection(pages: int = 2, headless: bool = False):
    if not PROFILE_LOCK.acquire(blocking=False):
        return {"accepted": False, "message": "抖音采集或查看窗口正在使用中，请关闭抖音Chrome窗口后重试"}
    pages = max(1, min(pages, 5))
    run_id = start_run("douyin", pages)

    def worker():
        total = 0
        try:
            items = asyncio.run(collect_douyin_opportunities(pages=pages, headless=headless))
            stamp = datetime.now(timezone.utc).isoformat()
            for item in items:
                upsert_douyin_opportunity(item, stamp)
                total += 1
            finish_run(run_id, "success", total)
        except Exception as exc:
            finish_run(run_id, "failed", total, f"{type(exc).__name__}: {exc}")
        finally:
            PROFILE_LOCK.release()

    threading.Thread(target=worker, name=f"douyin-collector-{run_id}", daemon=True).start()
    return {"accepted": True, "run_id": run_id, "pages": pages}
