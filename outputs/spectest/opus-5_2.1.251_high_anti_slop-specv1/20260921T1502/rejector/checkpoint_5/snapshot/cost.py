"""Cost accounting: what a run spends and the budget that stops it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from config import Cost

# Enough decimals to keep a single cheap call visible in the summary.
PLACES = 6


@dataclass
class Ledger:
    """One task's running spend, priced by its own rates.

    A task without a `cost` block keeps a ledger that records nothing, so the
    run can price every call the same way without asking whether it should.
    """

    cost: Cost | None
    prompt: float = field(default=0.0, init=False)
    completion: float = field(default=0.0, init=False)

    def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Price one API call and add it to the running total."""
        if self.cost is None:
            return
        self.prompt += prompt_tokens / 1000 * self.cost.prompt_per_1k
        self.completion += completion_tokens / 1000 * self.cost.completion_per_1k

    @property
    def total(self) -> float:
        return self.prompt + self.completion

    @property
    def exhausted(self) -> bool:
        """Whether the budget is spent, which stops the task from sending more."""
        if self.cost is None or self.cost.budget is None:
            return False
        return self.total >= self.cost.budget


def summarize_cost(ledgers: Iterable[Ledger]) -> dict | None:
    """The summary's `cost` object, or None when no task tracked cost.

    Each task spends against its own budget, so the run reports what they add
    up to and whether any of them ran out.
    """
    tracked = [ledger for ledger in ledgers if ledger.cost is not None]
    if not tracked:
        return None

    total = sum(ledger.total for ledger in tracked)
    budgets = [ledger.cost.budget for ledger in tracked if ledger.cost.budget is not None]
    budget = sum(budgets) if budgets else None
    return {
        "total": round(total, PLACES),
        "prompt": round(sum(ledger.prompt for ledger in tracked), PLACES),
        "completion": round(sum(ledger.completion for ledger in tracked), PLACES),
        "budget": budget,
        "budget_remaining": None if budget is None else round(budget - total, PLACES),
        "budget_exceeded": any(ledger.exhausted for ledger in tracked),
    }
