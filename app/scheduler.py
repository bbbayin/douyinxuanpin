import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from .db import get_settings
from .service import run_collection


class CollectionScheduler:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True, name="collection-scheduler")
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _loop(self):
        while not self.stop_event.wait(60):
            settings = get_settings()
            if not settings["auto_enabled"]:
                continue
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            if now.hour < settings["daily_start_hour"]:
                continue
            if settings["last_cycle_date"] == now.date().isoformat():
                continue
            # run_collection enforces the 30-minute inter-batch cooldown.
            run_collection("live", headless=True)


scheduler = CollectionScheduler()
