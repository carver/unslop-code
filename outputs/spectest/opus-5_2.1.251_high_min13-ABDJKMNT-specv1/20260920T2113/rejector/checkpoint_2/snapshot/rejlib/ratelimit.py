"""Request pacing against the server's stated capacity."""

from __future__ import annotations

import asyncio


class RateLimiter:
    """Token bucket admitting ``rpm`` requests per minute, bursting up to one
    minute's worth of budget so short runs are not paced artificially (T1).

    Acquisition is serialised by a lock, so waiters are admitted in the order
    they arrived - that is what keeps requests leaving in input order.
    """

    def __init__(self, rpm: int):
        self._interval = 60.0 / rpm
        self._capacity = float(rpm)
        self._tokens = float(rpm)
        self._updated: float | None = None
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request may be sent, then consume one token."""
        loop = asyncio.get_running_loop()
        async with self._lock:
            self._refill(loop.time())
            if self._tokens < 1.0:
                await asyncio.sleep((1.0 - self._tokens) * self._interval)
                self._refill(loop.time())
            self._tokens -= 1.0

    def _refill(self, now: float) -> None:
        elapsed = 0.0 if self._updated is None else now - self._updated
        self._tokens = min(self._capacity, self._tokens + elapsed / self._interval)
        self._updated = now
