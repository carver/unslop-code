"""Token-aware scheduling: sliding RPM and TPM windows plus a concurrency cap.

One limiter serves one task. Every request it admits leaves an entry in a
60-second window carrying the tokens that request was reserved against; when
the response arrives the entry is rewritten with the usage the API reported,
so the window tracks real consumption without ever double counting a request.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from math import ceil
from typing import Iterable

WINDOW_SECONDS = 60.0
WORDS_PER_TOKEN = 0.75
MAX_IN_FLIGHT = 256


@dataclass(frozen=True)
class RateLimits:
    """A task's scheduling budgets; `None` means the budget is not enforced."""

    rpm: int | None = None
    tpm: int | None = None
    max_concurrent: int | None = None

    @property
    def concurrency(self) -> int:
        """How many requests may be in flight at once.

        `max_concurrent` is a hard cap. Without one, the earlier fan-out rule
        stands: a minute's worth of requests, bounded so an unlimited task
        still keeps the connection pool finite.
        """
        fan_out = min(self.rpm or MAX_IN_FLIGHT, MAX_IN_FLIGHT)
        return self.max_concurrent or max(1, fan_out)


@dataclass
class Reservation:
    """One request's place in the token window, rewritten once usage is known."""

    at: float
    tokens: int


def estimate_prompt_tokens(texts: Iterable[str]) -> int:
    """The prompt token estimate for the text a request will send."""
    words = sum(len(text.split()) for text in texts if text)
    return ceil(words / WORDS_PER_TOKEN)


class RateLimiter:
    """Admits requests only while RPM, TPM and concurrency all have room.

    Admissions are serialised, so requests that had to wait are let through in
    the order they arrived and a task keeps dispatching its rows in order.
    """

    def __init__(self, limits: RateLimits):
        self._limits = limits
        self._window: deque[Reservation] = deque()
        self._gate = asyncio.Lock()
        self._freed = asyncio.Event()
        self.slots = asyncio.Semaphore(limits.concurrency)

    async def reserve(self, tokens: int) -> Reservation:
        """Wait for both budgets, then claim `tokens` for the next request."""
        async with self._gate:
            while (delay := self._delay(tokens)) > 0:
                await self._wait(delay)
            reservation = Reservation(time.monotonic(), tokens)
            self._window.append(reservation)
            return reservation

    def record(self, reservation: Reservation, tokens: int) -> None:
        """Replace a reservation with the usage the API actually reported."""
        reservation.tokens = tokens
        self._freed.set()

    async def _wait(self, delay: float) -> None:
        """Sleep until the window slides, or until a response frees space."""
        self._freed.clear()
        try:
            await asyncio.wait_for(self._freed.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    def _delay(self, tokens: int) -> float:
        """How long the next request has to wait, or 0.0 if it may go now."""
        now = time.monotonic()
        self._expire(now)
        if not self._window:
            return 0.0

        limits = self._limits
        over_requests = limits.rpm is not None and len(self._window) >= limits.rpm
        used = sum(entry.tokens for entry in self._window)
        over_tokens = limits.tpm is not None and used + tokens > limits.tpm
        if over_requests or over_tokens:
            return self._window[0].at + WINDOW_SECONDS - now
        return 0.0

    def _expire(self, now: float) -> None:
        """Drop the entries that have slid out of the 60-second window."""
        cutoff = now - WINDOW_SECONDS
        while self._window and self._window[0].at <= cutoff:
            self._window.popleft()
