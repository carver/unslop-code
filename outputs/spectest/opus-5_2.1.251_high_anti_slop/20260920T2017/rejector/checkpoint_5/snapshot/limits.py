"""Token-aware pacing: sliding request and token windows, and a concurrency cap.

A task's `rate_limits` are enforced by one `RequestLimiter`. Every HTTP request
books a slot in the request window and its estimated tokens in the token
window; once the API answers, the booking is corrected to the tokens the
response actually reported.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, AsyncContextManager

from config import RateLimits

#: Both budgets are spends per sliding minute.
WINDOW_SECONDS = 60.0
#: A waiting request re-checks its budgets this often: a response that used
#: fewer tokens than its estimate frees capacity before the window slides on.
RECHECK_SECONDS = 0.25
#: The prompt-token estimate used before a response reports the real count.
WORDS_PER_TOKEN = 0.75


def count_words(messages: list[dict[str, Any]]) -> int:
    """Words across every message that carries content."""
    return sum(len(message["content"].split()) for message in messages if message.get("content"))


def estimate_prompt_tokens(messages: list[dict[str, Any]]) -> int:
    """The prompt tokens a request is expected to use, rounded up."""
    return math.ceil(count_words(messages) / WORDS_PER_TOKEN)


@dataclass
class Booking:
    """One amount spent in a window: when it was spent, and how much."""

    at: float
    amount: float


@dataclass(frozen=True)
class Reservation:
    """The token booking one request made before it was sent."""

    booking: Booking

    def record(self, tokens: int) -> None:
        """Replace the estimate with the token count the API reported."""
        self.booking.amount = tokens


class SlidingWindow:
    """What has been spent in the last `WINDOW_SECONDS`, against an optional limit.

    A `None` limit is unlimited: spends are still recorded, but nothing ever
    waits for them.
    """

    def __init__(self, limit: int | None) -> None:
        self._limit = limit
        self._bookings: deque[Booking] = deque()

    def delay(self, now: float, amount: float) -> float:
        """Seconds until `amount` fits in the window; 0.0 when it fits already.

        An empty window always has room, so a single request larger than the
        whole limit is sent rather than waited on forever.
        """
        self._expire(now)
        total = sum(booking.amount for booking in self._bookings)
        if self._limit is None or not self._bookings or total + amount <= self._limit:
            return 0.0
        return self._bookings[0].at + WINDOW_SECONDS - now

    def add(self, now: float, amount: float) -> Booking:
        """Spend `amount` at `now`, returning the booking so it can be corrected."""
        booking = Booking(now, amount)
        self._bookings.append(booking)
        return booking

    def _expire(self, now: float) -> None:
        while self._bookings and self._bookings[0].at <= now - WINDOW_SECONDS:
            self._bookings.popleft()


class RequestLimiter:
    """Admits requests only while every configured budget has room.

    Requests and tokens are paced by windows of their own, so the tighter of
    `rpm` and `tpm` is what a run settles at; `max_concurrent` separately caps
    how much work is in flight. Callers queue behind one another on a lock,
    which keeps admissions ordered and stops two callers claiming the same
    capacity.
    """

    def __init__(self, limits: RateLimits) -> None:
        self._requests = SlidingWindow(limits.rpm)
        self._tokens = SlidingWindow(limits.tpm)
        self._slots = asyncio.Semaphore(limits.max_concurrent) if limits.max_concurrent else None
        self._lock = asyncio.Lock()

    def in_flight(self) -> AsyncContextManager[Any]:
        """Hold one concurrency slot for a unit of work.

        A unit is one request, or a whole agentic loop: the loop keeps its slot
        across every iteration it makes.
        """
        return self._slots or nullcontext()

    async def reserve(self, tokens: int) -> Reservation:
        """Wait for request and token capacity, then book `tokens` for this request."""
        async with self._lock:
            while True:
                now = time.monotonic()
                delay = max(self._requests.delay(now, 1), self._tokens.delay(now, tokens))
                if delay <= 0:
                    self._requests.add(now, 1)
                    return Reservation(self._tokens.add(now, tokens))
                await asyncio.sleep(min(delay, RECHECK_SECONDS))
