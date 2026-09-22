"""Request pacing for the configured requests-per-minute budget."""

import asyncio
import time

#: Fraction of the per-minute budget that may be spent immediately to fill the pipeline.
BURST_FRACTION = 10


class RateLimiter:
    """Token bucket admitting at most ``rpm`` requests per minute.

    Tokens accumulate up to a small burst so a run ramps up to the server's
    capacity at once instead of trickling, while the long-run rate stays at the
    configured budget. Waiters are served one at a time, in arrival order.
    """

    def __init__(self, rpm: int) -> None:
        self._interval = 60.0 / rpm
        self._burst = max(1, rpm // BURST_FRACTION)
        self._tokens = float(self._burst)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request slot is available, then consume it."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1.0 - self._tokens) * self._interval)

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self._burst, self._tokens + (now - self._updated) / self._interval)
        self._updated = now
