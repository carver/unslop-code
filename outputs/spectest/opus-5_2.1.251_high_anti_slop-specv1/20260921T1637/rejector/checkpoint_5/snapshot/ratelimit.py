"""Request pacing against the configured requests-per-minute and tokens-per-minute budgets."""

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterable, Mapping

from config import RateLimits

#: Length of the sliding window both budgets are measured over.
WINDOW_SECONDS = 60.0
#: Words one token is worth when estimating a prompt before it is sent.
WORDS_PER_TOKEN = 0.75
#: How long a blocked request waits before re-checking a budget that nothing has freed.
MIN_SLEEP_SECONDS = 0.005


def estimate_prompt_tokens(messages: Iterable[Mapping[str, object]]) -> int:
    """Estimate what a rendered conversation will cost from the words it contains."""
    words = sum(len(str(message.get("content") or "").split()) for message in messages)
    return math.ceil(words / WORDS_PER_TOKEN)


@dataclass
class _Entry:
    """One recorded amount and when it entered the window."""

    at: float
    amount: float


class _Window:
    """The amounts recorded over the last :data:`WINDOW_SECONDS`, capped at ``limit``.

    An unset budget becomes an infinite limit, so the window still records what
    was spent but never makes anyone wait for it.
    """

    def __init__(self, limit: int | None) -> None:
        self._limit = float(limit) if limit else math.inf
        self._entries: deque[_Entry] = deque()
        self._used = 0.0

    def add(self, amount: float) -> _Entry:
        """Record ``amount`` as spent from now, without checking the limit."""
        entry = _Entry(time.monotonic(), amount)
        self._entries.append(entry)
        self._used += amount
        return entry

    def adjust(self, entry: _Entry, amount: float) -> None:
        """Replace what ``entry`` booked with the amount actually spent."""
        self._used += amount - entry.amount
        entry.amount = amount

    def delay(self, amount: float) -> float:
        """Seconds to wait before ``amount`` fits; ``0`` when it fits now.

        An amount larger than the whole budget is admitted once the window
        empties, since no amount of waiting would ever make room for it.
        """
        self._expire()
        if self._used + amount <= self._limit or not self._entries:
            return 0.0
        return max(self._entries[0].at + WINDOW_SECONDS - time.monotonic(), MIN_SLEEP_SECONDS)

    def _expire(self) -> None:
        cutoff = time.monotonic() - WINDOW_SECONDS
        while self._entries and self._entries[0].at <= cutoff:
            self._used -= self._entries.popleft().amount


@dataclass(frozen=True)
class Reservation:
    """Tokens booked for one request, settled against its real usage afterwards."""

    window: _Window
    entry: _Entry

    def settle(self, tokens: int) -> None:
        """Record the tokens the response actually reported in place of the estimate."""
        self.window.adjust(self.entry, tokens)


class RateLimiter:
    """Admits a task's requests only while both of its budgets have capacity.

    Requests and tokens are tracked in separate sliding windows, and a request
    waits until it fits in both. Waiters are served one at a time in arrival
    order, so a row that asked first is dispatched first.
    """

    def __init__(self, limits: RateLimits) -> None:
        self._requests = _Window(limits.rpm)
        self._tokens = _Window(limits.tpm)
        self._lock = asyncio.Lock()

    async def reserve(self, tokens: int) -> Reservation:
        """Wait for room for one request and ``tokens``, then book both."""
        async with self._lock:
            while True:
                delay = max(self._requests.delay(1), self._tokens.delay(tokens))
                if delay == 0:
                    self._requests.add(1)
                    return Reservation(self._tokens, self._tokens.add(tokens))
                await asyncio.sleep(delay)
