import asyncio
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .collectors.alibaba1688 import collect_keywords
from .collectors.demo import collect_demo
from .db import finish_run, get_settings, list_keywords, recent_runs, save_keyword_cursor, save_last_cycle_date, start_run, upsert_product


_lock = threading.Lock()
_demo_round = 0
LIVE_COOLDOWN_MINUTES = 30
_scheduled_timer = None


def live_cooldown_seconds() -> int:
    live_runs = [run for run in recent_runs(20) if run["mode"] == "live"]
    if not live_runs:
        return 0
    last_started = datetime.fromisoformat(live_runs[0]["started_at"])
    elapsed = (datetime.now(timezone.utc) - last_started).total_seconds()
    return max(0, round(LIVE_COOLDOWN_MINUTES * 60 - elapsed))


def schedule_live_after_cooldown():
    global _scheduled_timer
    if _scheduled_timer and _scheduled_timer.is_alive():
        return {"accepted": False, "message": "已经预约了一次真实采集"}
    delay = live_cooldown_seconds() + 10
    if delay <= 10:
        return run_collection("live", headless=False)
    _scheduled_timer = threading.Timer(delay, lambda: run_collection("live", headless=False))
    _scheduled_timer.daemon = True
    _scheduled_timer.start()
    scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    return {
        "accepted": True,
        "scheduled": True,
        "delay_seconds": delay,
        "scheduled_at": scheduled_at.isoformat(),
    }


def run_collection(mode: str = "live", headless: bool = False):
    global _demo_round
    if mode == "live":
        remaining_seconds = live_cooldown_seconds()
        if remaining_seconds:
            remaining = max(1, round(remaining_seconds / 60))
            return {"accepted": False, "message": f"为降低1688风控风险，请等待约{remaining}分钟后再采集"}
    if not _lock.acquire(blocking=False):
        return {"accepted": False, "message": "已有采集任务正在运行"}
    all_words = [row["value"] for row in list_keywords() if row["enabled"]]
    settings = get_settings()
    if mode == "live" and all_words:
        cursor = settings["keyword_cursor"] % len(all_words)
        count = min(settings["batch_size"], len(all_words))
        words = all_words[cursor:min(cursor + count, len(all_words))]
    else:
        cursor = 0
        words = all_words
    run_id = start_run(mode, len(words))

    def worker():
        global _demo_round
        total = 0
        try:
            if mode == "demo":
                _demo_round += 1
                # Demo snapshots are spaced by 24 hours so growth is immediately visible.
                stamp = (datetime.now(timezone.utc) + timedelta(days=_demo_round - 1)).isoformat()
                for word in words:
                    items = asyncio.run(collect_demo(word, round_no=_demo_round))
                    for item in items:
                        upsert_product(item, word, stamp)
                        total += 1
            else:
                batches = asyncio.run(collect_keywords(
                    words,
                    headless=headless,
                    min_delay_seconds=settings["min_delay_seconds"],
                    pages_per_keyword=settings["pages_per_keyword"],
                ))
                stamp = datetime.now(timezone.utc).isoformat()
                for word, items in batches.items():
                    for item in items:
                        upsert_product(item, word, stamp)
                        total += 1
                if total == 0:
                    raise RuntimeError("1688 页面未解析到任何商品")
                next_cursor = cursor + len(words)
                cycle_finished = next_cursor >= len(all_words)
                save_keyword_cursor(0 if cycle_finished else next_cursor)
                if cycle_finished:
                    save_last_cycle_date(datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
            finish_run(run_id, "success", total)
        except Exception as exc:
            finish_run(run_id, "failed", total, f"{type(exc).__name__}: {exc}")
        finally:
            _lock.release()

    threading.Thread(target=worker, name=f"collector-{run_id}", daemon=True).start()
    return {"accepted": True, "run_id": run_id, "keyword_count": len(words)}
