"""The running cost of a run, and the budget that stops it.

Every API call is charged at its own task's rates into one tracker shared by
the whole run, so judge calls and agentic iterations are counted alongside the
generations they belong to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import CostConfig, TaskConfig


class BudgetExhausted(Exception):
    """The run's budget is spent, so no further request may be sent.

    Raised in place of a request rather than reported as an error: the rows
    that did finish are still written and the run exits successfully.
    """


@dataclass
class CostTracker:
    """What a run has spent so far, and whether it may spend more.

    `configured` records whether any task asked for cost tracking at all, which
    decides whether the summary reports it. `budget` is the run's cap, taken
    from the tasks that set one.
    """

    budget: float | None = None
    configured: bool = False
    prompt: float = 0.0
    completion: float = 0.0

    @property
    def total(self) -> float:
        return self.prompt + self.completion

    @property
    def exceeded(self) -> bool:
        return self.budget is not None and self.total >= self.budget

    def charge(self, rates: CostConfig, prompt_tokens: int, completion_tokens: int) -> None:
        """Add one API call's cost at the calling task's rates."""
        self.prompt += prompt_tokens / 1000 * rates.prompt_cost_per_1k
        self.completion += completion_tokens / 1000 * rates.completion_cost_per_1k

    def check(self) -> None:
        """Refuse a request once the budget is spent.

        Raises:
            BudgetExhausted: the running total has reached the budget.
        """
        if self.exceeded:
            raise BudgetExhausted(f"budget of {self.budget} spent")

    def summary(self) -> dict[str, Any]:
        """The `cost` object of the run summary."""
        remaining = None if self.budget is None else round(self.budget - self.total, 2)
        return {
            "total": round(self.total, 2),
            "prompt": round(self.prompt, 2),
            "completion": round(self.completion, 2),
            "budget": self.budget,
            "budget_remaining": remaining,
            "budget_exceeded": self.exceeded,
        }


def tracker_for(tasks: list[TaskConfig]) -> CostTracker:
    """The run's shared tracker; its budget is the lowest any task sets."""
    budgets = [task.cost.budget for task in tasks if task.cost and task.cost.budget is not None]
    return CostTracker(
        budget=min(budgets, default=None),
        configured=any(task.cost is not None for task in tasks),
    )

