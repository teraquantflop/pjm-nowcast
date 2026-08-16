"""In-memory token bucket. Single instance only."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock


class TokenBucket:
    def __init__(self, rate: float, burst: int) -> None:
        self.rate = max(rate, 0.01)
        self.burst = max(burst, 1)
        self._tokens: dict[str, float] = defaultdict(lambda: float(self.burst))
        self._ts: dict[str, float] = defaultdict(time.monotonic)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._ts[key]
            tokens = min(self.burst, self._tokens[key] + (now - last) * self.rate)
            self._ts[key] = now
            if tokens < 1.0:
                self._tokens[key] = tokens
                return False
            self._tokens[key] = tokens - 1.0
            return True
