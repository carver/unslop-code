"""Rate limiting and the gate every outgoing API request passes through.

RPM and TPM are sliding 60-second windows: a request is admitted only once
both windows have room for it. Tokens are *reserved* from an estimate before
dispatch and the reservation is rewritten to the response's real usage when it
arrives, so the window always reflects what was actually spent.
"""

from __future__ import annotations

import asyncio
import contextvars
import math
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Mapping, Sequence

from .config import CostConfig, RateLimitConfig
from .cost import CostTracker

WINDOW_SECONDS = 60.0
# The spec's prompt-token estimate: one token is about three quarters of a word.
WORDS_PER_TOKEN = 0.75
# Ceiling on in-flight requests when a task configures no `max_concurrent`.
UNCAPPED_CONCURRENCY = 256

# Set while a caller holds a concurrency slot, so requests made inside an
# agentic loop reuse the slot the loop already took rather than queueing for
# one of their own.
_HOLDS_SLOT = contextvars.ContextVar("limits_holds_slot", default=False)


def estimate_prompt_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    """Prompt tokens a rendered conversation is expected to cost."""
    words = sum(len(str(message.get("content") or "").split()) for message in messages)
    return math.ceil(words / WORDS_PER_TOKEN)


@dataclass
class Entry:
    """One amount spent at one moment, until it slides out of the window."""

    at: float
    amount: int


class SlidingWindow:
    """How much of a per-60-second budget the recent past has used."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._entries: deque[Entry] = deque()

    def used(self, now: float) -> int:
        self._expire(now)
        return sum(entry.amount for entry in self._entries)

    def delay(self, amount: int, now: float) -> float:
        """Seconds until `amount` fits, or 0.0 when it already does.

        An amount larger than the whole budget is admitted against an empty
        window rather than waiting forever.
        """
        used = self.used(now)
        if not self._entries or used + amount <= self.limit:
            return 0.0
        freed = 0
        for entry in self._entries:
            freed += entry.amount
            if used - freed + amount <= self.limit:
                return entry.at + WINDOW_SECONDS - now
        return self._entries[-1].at + WINDOW_SECONDS - now

    def spend(self, amount: int, now: float) -> Entry:
        entry = Entry(now, amount)
        self._entries.append(entry)
        return entry

    def _expire(self, now: float) -> None:
        while self._entries and self._entries[0].at <= now - WINDOW_SECONDS:
            self._entries.popleft()


@dataclass
class Reservation:
    """The token window entry a dispatched request is holding."""

    entry: Entry | None

    def settle(self, tokens: int) -> None:
        """Replace the estimate with the usage the response reported."""
        if self.entry is not None:
            self.entry.amount = tokens


class RateLimiter:
    """One task's RPM window, TPM window and in-flight cap."""

    def __init__(self, limits: RateLimitConfig) -> None:
        self.requests = SlidingWindow(limits.rpm) if limits.rpm else None
        self.tokens = SlidingWindow(limits.tpm) if limits.tpm else None
        self._slots = asyncio.Semaphore(limits.max_concurrent or UNCAPPED_CONCURRENCY)
        self._admission = asyncio.Lock()

    def delay(self, tokens: int, now: float) -> float:
        """Seconds before both budgets have room for one request of `tokens`."""
        return max(
            self.requests.delay(1, now) if self.requests else 0.0,
            self.tokens.delay(tokens, now) if self.tokens else 0.0,
        )

    async def reserve(self, tokens: int) -> Reservation:
        """Wait for room in both windows, then claim it for one request.

        Admission is serialised, so requests leave in the order they queued.
        """
        async with self._admission:
            while True:
                wait = self.delay(tokens, time.monotonic())
                if wait <= 0:
                    break
                await asyncio.sleep(wait)
            now = time.monotonic()
            if self.requests is not None:
                self.requests.spend(1, now)
            return Reservation(self.tokens.spend(tokens, now) if self.tokens else None)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold one in-flight slot, reusing an enclosing one if there is one."""
        if _HOLDS_SLOT.get():
            yield
            return
        marker = _HOLDS_SLOT.set(True)
        try:
            async with self._slots:
                yield
        finally:
            _HOLDS_SLOT.reset(marker)


@dataclass
class CallWindow:
    """Spans the first request sent to the last response received."""

    first: float | None = field(default=None)
    last: float | None = field(default=None)

    def record(self, start: float, end: float) -> None:
        self.first = start if self.first is None else min(self.first, start)
        self.last = end if self.last is None else max(self.last, end)

    @property
    def elapsed(self) -> float:
        return 0.0 if self.first is None else self.last - self.first


@dataclass(frozen=True)
class RequestGate:
    """What a task's requests are admitted and charged against.

    A task and its judge share one gate; every task shares the run's cost
    tracker and timing window.
    """

    limiter: RateLimiter
    tracker: CostTracker
    rates: CostConfig | None
    window: CallWindow

    @property
    def stopped(self) -> bool:
        """True once the run's budget is spent and no request may be sent."""
        return self.tracker.exhausted

    def charge(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Count one answered call and price it at this task's rates."""
        self.tracker.calls += 1
        if self.rates is not None:
            self.tracker.charge(prompt_tokens, completion_tokens, self.rates)
