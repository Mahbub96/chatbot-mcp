from __future__ import annotations

import time


class InMemoryRateLimiter:
    def __init__(self, window_seconds: int, max_requests: int):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self._request_tracker: dict[str, list[float]] = {}

    def is_limited(self, key: str) -> bool:
        now = time.time()
        timestamps = self._request_tracker.get(key, [])
        fresh = [ts for ts in timestamps if (now - ts) < self.window_seconds]

        if len(fresh) >= self.max_requests:
            self._request_tracker[key] = fresh
            return True

        fresh.append(now)
        self._request_tracker[key] = fresh
        return False

