import asyncio
import threading
from datetime import datetime, timezone

from .collectors.douyin import collect_douyin_opportunities
from .db import finish_run, start_run, upsert_douyin_opportunity


_lock = threading.Lock()


def run_douyin_collection(pages: int = 2, headless: bool = False):
    if not _lock.acquire(blocking=False):
        return {"accepted": False, "message": "抖音商机采集正在运行"}
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
            _lock.release()

    threading.Thread(target=worker, name=f"douyin-collector-{run_id}", daemon=True).start()
    return {"accepted": True, "run_id": run_id, "pages": pages}
