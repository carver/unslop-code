"""Pacing requests against sliding one minute request and token budgets."""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass

from config import RateLimits

WINDOW_SECONDS = 60.0
# The prompt size estimate the scheduler works with before a response exists.
WORDS_PER_TOKEN = 0.75


def estimate_tokens(messages: list[dict]) -> int:
    """Estimate the prompt size of a conversation from the words it carries."""
    words = sum(len(str(message["content"]).split()) for message in messages if message["content"])
    return math.ceil(words / WORDS_PER_TOKEN)


@dataclass
class Reservation:
    """One request's place in the token window.

    It starts out holding the estimate the scheduler reserved and is settled
    with the usage the API reported once the response arrives.
    """

    at: float
    tokens: int

    def settle(self, tokens: int) -> None:
        self.tokens = tokens


class Limiter:
    """Holds requests back until both of a task's sliding budgets have room.

    Waiters queue on the lock, so requests start in the order they were
    submitted. A budget left out of the config is simply not enforced.
    """

    def __init__(self, limits: RateLimits) -> None:
        self._rpm = limits.rpm
        self._tpm = limits.tpm
        self._requests: deque[float] = deque()
        self._tokens: deque[Reservation] = deque()
        self._lock = asyncio.Lock()

    async def reserve(self, tokens: int) -> Reservation:
        """Wait for room for a request of `tokens`, then record it as sent."""
        async with self._lock:
            while True:
                now = time.monotonic()
                self._expire(now)
                delay = self._delay(tokens, now)
                if delay is None:
                    break
                await asyncio.sleep(delay)

            reservation = Reservation(now, tokens)
            if self._rpm is not None:
                self._requests.append(now)
            if self._tpm is not None:
                self._tokens.append(reservation)
            return reservation

    def _expire(self, now: float) -> None:
        """Drop what has fallen out of the trailing minute."""
        horizon = now - WINDOW_SECONDS
        while self._requests and self._requests[0] <= horizon:
            self._requests.popleft()
        while self._tokens and self._tokens[0].at <= horizon:
            self._tokens.popleft()

    def _delay(self, tokens: int, now: float) -> float | None:
        """How long until the windows might fit this request; None when they do now.

        Waiting for the oldest entry of a full window to age out is the soonest
        anything can change; the caller re-checks afterwards.
        """
        waits = []
        if self._rpm is not None and len(self._requests) >= self._rpm:
            waits.append(self._requests[0] + WINDOW_SECONDS - now)
        if self._tpm is not None and self._tokens and self._spent() + tokens > self._tpm:
            waits.append(self._tokens[0].at + WINDOW_SECONDS - now)
        return max(waits) if waits else None

    def _spent(self) -> int:
        return sum(reservation.tokens for reservation in self._tokens)
