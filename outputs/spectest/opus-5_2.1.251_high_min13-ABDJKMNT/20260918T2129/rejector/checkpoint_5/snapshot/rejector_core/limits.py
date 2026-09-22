"""Token-aware scheduling: sliding request/token windows and in-flight slots.

Each task owns one `RateLimiter`.  Requests are admitted only when both the
request window and the token window have room, and every row (or agentic
loop) holds one of the limiter's concurrency slots while it runs.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque

from .config import RateLimits

WINDOW_SECONDS = 60.0
WORDS_PER_TOKEN = 0.75


def estimate_prompt_tokens(payload: dict) -> int:
    """Prompt tokens for a request, from the words of its rendered messages.

    Completions-mode payloads carry one rendered `prompt` string instead of a
    message list; both are measured the same way.
    """
    texts = [payload["prompt"]] if "prompt" in payload else _contents(payload["messages"])
    return math.ceil(sum(len(text.split()) for text in texts) / WORDS_PER_TOKEN)


def _contents(messages: list[dict]) -> list[str]:
    """The text of every message; a tool-call turn has none."""
    return [message.get("content") or "" for message in messages]


class _Window:
    """A sliding `WINDOW_SECONDS` budget of requests or tokens."""

    def __init__(self, limit: int):
        self._limit = limit
        self._entries: deque[list] = deque()
        self._used = 0

    def delay(self, amount: int) -> float:
        """Seconds until `amount` fits; zero when it fits right now.

        An amount larger than the whole budget is treated as the whole
        budget, so an oversized request waits for an empty window rather
        than never being sent.
        """
        self._expire()
        if self._used + min(amount, self._limit) <= self._limit:
            return 0.0
        return self._entries[0][0] + WINDOW_SECONDS - time.monotonic()

    def add(self, amount: int) -> list:
        """Book `amount` against the window and return its entry."""
        entry = [time.monotonic(), amount]
        self._entries.append(entry)
        self._used += amount
        return entry

    def settle(self, entry: list, amount: int) -> None:
        """Replace a booked estimate with what the request actually used."""
        self._used += amount - entry[1]
        entry[1] = amount

    def _expire(self) -> None:
        cutoff = time.monotonic() - WINDOW_SECONDS
        while self._entries and self._entries[0][0] <= cutoff:
            self._used -= self._entries.popleft()[1]


class Reservation:
    """Tokens booked for one request before it was dispatched."""

    def __init__(self, window: _Window | None, entry: list | None):
        self._window = window
        self._entry = entry

    def settle(self, actual_tokens: int) -> None:
        """Record the response's real token usage in place of the estimate."""
        if self._window is not None:
            self._window.settle(self._entry, actual_tokens)


class RateLimiter:
    """Paces one task against its RPM, TPM, and concurrency budgets.

    `fallback_concurrency` is used when the task configures no
    `max_concurrent`, keeping the request budget derived from `rpm` that
    earlier checkpoints relied on.
    """

    def __init__(self, limits: RateLimits, fallback_concurrency: int):
        self.concurrency = limits.max_concurrent or fallback_concurrency
        self._requests = _Window(limits.rpm) if limits.rpm else None
        self._tokens = _Window(limits.tpm) if limits.tpm else None
        self._slots = asyncio.Semaphore(self.concurrency)
        self._gate = asyncio.Lock()

    def slot(self) -> asyncio.Semaphore:
        """One of the `max_concurrent` in-flight slots, held as a context."""
        return self._slots

    async def reserve(self, tokens: int) -> Reservation:
        """Wait until both budgets have capacity, then book this request."""
        async with self._gate:
            while True:
                delay = max(self._delay(self._requests, 1), self._delay(self._tokens, tokens))
                if delay <= 0:
                    break
                await asyncio.sleep(delay)

            if self._requests is not None:
                self._requests.add(1)
            entry = self._tokens.add(tokens) if self._tokens is not None else None
            return Reservation(self._tokens, entry)

    @staticmethod
    def _delay(window: _Window | None, amount: int) -> float:
        return 0.0 if window is None else window.delay(amount)
