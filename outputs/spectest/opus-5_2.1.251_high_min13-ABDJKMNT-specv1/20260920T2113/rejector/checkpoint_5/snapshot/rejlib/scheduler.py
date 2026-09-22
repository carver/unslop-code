"""What gates one task's requests: its rate budgets, its concurrency cap, and
the run-wide cost ledger."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from rejlib.config import RateLimits
from rejlib.cost import CostConfig, Ledger
from rejlib.ratelimit import Concurrency, Entry, RateLimiter


@dataclass(frozen=True)
class Pending:
    """An admitted request whose real token usage is not known yet."""

    limiter: RateLimiter
    reservation: Entry
    ledger: Ledger
    rates: CostConfig

    def settle(self, usage: dict) -> None:
        """Record the response's usage in the token window and bill it."""
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        self.limiter.settle(self.reservation, prompt + completion)
        self.ledger.charge(prompt, completion, self.rates)


class Scheduler:
    """Decides when one task may send a request, and what the reply costs.

    Judge calls and agentic iterations share their task's scheduler, so every
    request the task makes is paced, capped and billed the same way.
    """

    def __init__(self, limits: RateLimits, rates: CostConfig, ledger: Ledger):
        self._limiter = RateLimiter(limits.rpm, limits.tpm)
        self._concurrency = Concurrency(limits.max_concurrent)
        self._rates = rates
        self._ledger = ledger

    @property
    def exhausted(self) -> bool:
        """Whether the budget is spent, so no new request may be sent."""
        return self._ledger.exhausted

    def slot(self):
        """Hold one concurrency slot for as long as the block runs."""
        return self._concurrency.hold()

    @asynccontextmanager
    async def request(self, estimated_tokens: int):
        """Admit one request: a concurrency slot plus RPM and TPM capacity."""
        async with self._concurrency.hold():
            reservation = await self._limiter.reserve(estimated_tokens)
            yield Pending(self._limiter, reservation, self._ledger, self._rates)
