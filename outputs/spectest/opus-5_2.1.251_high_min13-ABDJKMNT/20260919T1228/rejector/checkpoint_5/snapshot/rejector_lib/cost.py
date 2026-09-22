"""Cost accounting: what each call costs and when the budget stops the run."""

from __future__ import annotations

from dataclasses import dataclass

CENTS = 6


@dataclass(frozen=True)
class CostRates:
    """One task's `cost` block: its per-1k prices and the run's budget."""

    prompt_per_1k: float = 0.0
    completion_per_1k: float = 0.0
    budget: float | None = None

    def price(self, prompt_tokens: int, completion_tokens: int) -> tuple[float, float]:
        """The prompt and completion cost of one API call."""
        return (
            prompt_tokens / 1000 * self.prompt_per_1k,
            completion_tokens / 1000 * self.completion_per_1k,
        )


class BudgetStop(Exception):
    """Raised in place of dispatching once the run's budget is spent."""


class CostTracker:
    """The run's running cost, shared by every task and every kind of call."""

    def __init__(self, budget: float | None = None, enabled: bool = False):
        self.budget = budget
        self.enabled = enabled
        self.prompt = 0.0
        self.completion = 0.0

    @property
    def total(self) -> float:
        return self.prompt + self.completion

    @property
    def exceeded(self) -> bool:
        return self.budget is not None and self.total >= self.budget

    def charge(self, prompt_cost: float, completion_cost: float) -> None:
        self.prompt += prompt_cost
        self.completion += completion_cost

    def ensure_open(self) -> None:
        """Refuse to dispatch another request once the budget is reached."""
        if self.exceeded:
            raise BudgetStop()

    def summary(self) -> dict:
        """The summary's `cost` block, for runs that track cost at all."""
        spare = None if self.budget is None else round(self.budget - self.total, CENTS)
        return {
            "total": round(self.total, CENTS),
            "prompt": round(self.prompt, CENTS),
            "completion": round(self.completion, CENTS),
            "budget": self.budget,
            "budget_remaining": spare,
            "budget_exceeded": self.exceeded,
        }


def track_run(rates: list[CostRates | None]) -> CostTracker:
    """The tracker for a run, given the `cost` block of each task in it.

    Costs are accumulated across all tasks against a single budget; when tasks
    configure different budgets the smallest one binds.
    """
    budgets = [rate.budget for rate in rates if rate and rate.budget is not None]
    return CostTracker(min(budgets, default=None), enabled=any(rates))
