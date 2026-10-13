"""Per-client sliding-window rate limit for the chat endpoint (answers cost money)."""

import time
from collections import deque


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float, clock=time.monotonic):
        self.max_requests = max_requests
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, client: str) -> float | None:
        """Record a request; None if allowed, else seconds until the next one is allowed."""
        if self.max_requests <= 0:
            return None
        now = self.clock()
        hits = self._hits.setdefault(client, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return round(self.window - (now - hits[0]), 1)
        hits.append(now)
        return None
