"""Request pacing: the sliding request and token windows a task's calls pass through.

Both windows cover the last 60 seconds. A request books the tokens it expects to
spend before it is dispatched, and that reservation is replaced by the count the
API reports once the response arrives, so the token budget follows real usage
without ever overshooting on a burst.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass

from templates import Message

#: Span both budgets are measured over.
WINDOW_SECONDS = 60.0
#: Rule of thumb for sizing a prompt before the API reports its real token count.
WORDS_PER_TOKEN = 0.75
#: In-flight requests allowed when neither `max_concurrent` nor `rpm` is configured.
DEFAULT_MAX_CONCURRENT = 10


@dataclass(frozen=True)
class RateLimits:
    """A task's request, token and concurrency budgets; `None` means unlimited."""

    rpm: int | None = None
    tpm: int | None = None
    max_concurrent: int = DEFAULT_MAX_CONCURRENT


class Reservation:
    """Units booked in a sliding window, adjustable once the real amount is known."""

    def __init__(self, at: float, amount: float) -> None:
        self.at = at
        self.amount = amount

    def settle(self, amount: float) -> None:
        """Replace the booked amount with what was actually spent."""
        self.amount = float(amount)


class SlidingWindow:
    """What has been spent in the last minute, measured against a per-minute limit."""

    def __init__(self, limit: int | None) -> None:
        self._limit = limit
        self._entries: list[Reservation] = []

    def delay_for(self, amount: float) -> float:
        """Seconds to wait before `amount` fits under the limit; zero when it fits now.

        Entries age out oldest first, so waiting for the oldest ones to leave the
        window is what frees the room a request needs. A single request larger
        than the whole limit waits for an empty window and then goes out.
        """
        if self._limit is None:
            return 0.0

        now = time.monotonic()
        self._entries = [entry for entry in self._entries if entry.at > now - WINDOW_SECONDS]
        spent = sum(entry.amount for entry in self._entries)
        needed = spent + min(amount, self._limit) - self._limit

        delay = 0.0
        freed = 0.0
        for entry in self._entries:
            if freed >= needed:
                break
            freed += entry.amount
            delay = entry.at + WINDOW_SECONDS - now
        return delay

    def add(self, amount: float) -> Reservation:
        """Book `amount` against the window from now on."""
        entry = Reservation(time.monotonic(), float(amount))
        if self._limit is not None:
            self._entries.append(entry)
        return entry


class RequestLimiter:
    """Paces one task's requests against its sliding request and token budgets.

    A request may go out only once both windows have room for it, which is what
    lets the tighter of the two budgets set the pace.
    """

    def __init__(self, limits: RateLimits) -> None:
        self._requests = SlidingWindow(limits.rpm)
        self._tokens = SlidingWindow(limits.tpm)
        self._lock = asyncio.Lock()

    async def reserve(self, tokens: int) -> Reservation:
        """Wait for room in both windows, then book a request and its expected tokens."""
        while True:
            async with self._lock:
                delay = max(self._requests.delay_for(1), self._tokens.delay_for(tokens))
                if delay <= 0.0:
                    self._requests.add(1)
                    return self._tokens.add(tokens)
            await asyncio.sleep(delay)


def estimate_tokens(messages: Sequence[Message]) -> int:
    """Prompt tokens a rendered conversation is expected to cost, rounded up."""
    words = sum(len(str(message.get("content") or "").split()) for message in messages)
    return math.ceil(words / WORDS_PER_TOKEN)
