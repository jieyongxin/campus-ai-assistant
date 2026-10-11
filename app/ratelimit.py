"""极简内存限流：按 IP 的滑动窗口。"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict


class RateLimiter:
    def __init__(self, per_minute: int = 30):
        self.per_minute = max(1, per_minute)
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > 60:
                bucket.popleft()
            if len(bucket) >= self.per_minute:
                return False
            bucket.append(now)
            if len(self._hits) > 5000:
                for k in [k for k, v in self._hits.items() if not v][:1000]:
                    self._hits.pop(k, None)
            return True
