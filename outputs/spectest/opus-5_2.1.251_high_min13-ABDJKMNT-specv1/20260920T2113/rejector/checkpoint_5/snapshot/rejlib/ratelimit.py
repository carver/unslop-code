"""Request pacing: sliding 60-second request and token budgets, plus the
hard cap on in-flight requests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

#: "a sliding 60-second window" / "a sliding 60-second token budget"
WINDOW = 60.0


@dataclass
class Entry:
    """One charge against a window: an amount, recorded at a point in time.

    A token entry starts out holding the reservation made before dispatch and is
    rewritten with the response's actual usage (T71).
    """

    at: float
    amount: float


class _Window:
    """What a sliding budget has spent in the last ``WINDOW`` seconds.

    ``limit`` of ``None`` disables the budget: every request is admitted at once
    and nothing is accumulated.
    """

    def __init__(self, limit: int | None):
        self._limit = limit
        self._entries: list[Entry] = []

    def delay(self, now: float, amount: float) -> float:
        """Seconds to wait before ``amount`` more fits inside the window."""
        if self._limit is None:
            return 0.0
        self._expire(now)
        spare = self._limit - sum(entry.amount for entry in self._entries)
        # A single request larger than the whole budget would never fit, so it
        # goes out alone once the window has drained (T72).
        if amount <= spare or not self._entries:
            return 0.0
        return max(0.0, self._drained_at(amount - spare) - now)

    def _drained_at(self, needed: float) -> float:
        """When enough of the oldest entries will have aged out to free ``needed``.

        An amount larger than the whole budget is only freed by the window
        emptying, which is when the newest entry ages out (T72).
        """
        freed = 0.0
        for entry in self._entries:
            freed += entry.amount
            if freed >= needed:
                return entry.at + WINDOW
        return self._entries[-1].at + WINDOW

    def add(self, now: float, amount: float) -> Entry:
        """Charge ``amount`` to the window as of ``now``."""
        entry = Entry(now, amount)
        if self._limit is not None:
            self._expire(now)
            self._entries.append(entry)
        return entry

    def _expire(self, now: float) -> None:
        cutoff = now - WINDOW
        self._entries = [entry for entry in self._entries if entry.at > cutoff]


class RateLimiter:
    """Admits requests while both the RPM and the TPM window have capacity.

    Admission is serialised by a lock, so waiters are admitted in the order they
    arrived - that is what keeps requests leaving in input order.
    """

    def __init__(self, rpm: int | None = None, tpm: int | None = None):
        self._requests = _Window(rpm)
        self._tokens = _Window(tpm)
        self._lock = asyncio.Lock()

    def delay(self, now: float, estimated_tokens: int) -> float:
        """How long a request reserving ``estimated_tokens`` has to wait."""
        return max(self._requests.delay(now, 1),
                   self._tokens.delay(now, estimated_tokens))

    def admit(self, now: float, estimated_tokens: int) -> Entry:
        """Record one request and its token reservation, and return the latter."""
        self._requests.add(now, 1)
        return self._tokens.add(now, estimated_tokens)

    async def reserve(self, estimated_tokens: int) -> Entry:
        """Wait until the request may be sent, then reserve its budget.

        The lock is held across the wait, so the capacity this waiter waited for
        cannot be taken by a later one.
        """
        loop = asyncio.get_running_loop()
        async with self._lock:
            wait = self.delay(loop.time(), estimated_tokens)
            if wait > 0:
                await asyncio.sleep(wait)
            return self.admit(loop.time(), estimated_tokens)

    def settle(self, reservation: Entry, tokens: int) -> None:
        """Replace a reservation with the usage the response actually reported."""
        reservation.amount = tokens


class Concurrency:
    """Hard cap on in-flight requests, independent of RPM and TPM.

    The hold is reentrant per asyncio task: an agentic loop takes the slot once
    and the requests it makes inside see it as already held, so one loop
    occupies one slot for its entire lifetime.
    """

    def __init__(self, limit: int | None = None):
        self._semaphore = asyncio.Semaphore(limit) if limit is not None else None
        self._holders: set[asyncio.Task] = set()

    @asynccontextmanager
    async def hold(self):
        """Occupy one slot for as long as the block runs."""
        task = asyncio.current_task()
        if self._semaphore is None or task in self._holders:
            yield
            return

        await self._semaphore.acquire()
        self._holders.add(task)
        try:
            yield
        finally:
            self._holders.discard(task)
            self._semaphore.release()
