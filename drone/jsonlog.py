"""JSON 라인 로그 (drone/logs/drone_YYYYMMDD.jsonl)."""
import json
import os
import threading
import time


class JsonLog:
    def __init__(self, log_dir):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._lock = threading.Lock()

    def path(self):
        return os.path.join(self.log_dir, "drone_%s.jsonl" % time.strftime("%Y%m%d"))

    def write(self, event, **fields):
        rec = {"ts": round(time.time(), 3), "event": event}
        rec.update(fields)
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.path(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return rec
