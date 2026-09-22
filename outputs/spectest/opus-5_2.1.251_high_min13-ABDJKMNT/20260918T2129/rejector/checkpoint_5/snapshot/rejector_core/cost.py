"""Cost accounting across every task, and the budget that stops the run."""

from __future__ import annotations

from collections.abc import Iterable

from .config import Cost, TaskConfig

MONEY_PLACES = 2


class CostTracker:
    """The run's running spend, charged at each task's own rates.

    `enabled` decides whether the summary carries a `cost` block; `budget` is
    run-wide, because the spec tracks cost "across all tasks".
    """

    def __init__(self, budget: float | None, enabled: bool):
        self.budget = budget
        self.enabled = enabled
        self.prompt = 0.0
        self.completion = 0.0

    def record(self, rates: Cost | None, prompt_tokens: int, completion_tokens: int) -> None:
        """Charge one API call to the run."""
        if rates is None:
            return
        self.prompt += prompt_tokens / 1000 * rates.prompt_cost_per_1k
        self.completion += completion_tokens / 1000 * rates.completion_cost_per_1k

    @property
    def total(self) -> float:
        return self.prompt + self.completion

    @property
    def exhausted(self) -> bool:
        """Whether the budget has been reached, so no new request may go out."""
        return self.budget is not None and self.total >= self.budget

    def summary(self) -> dict:
        """The summary's `cost` block."""
        remaining = None if self.budget is None else max(0.0, self.budget - self.total)
        return {
            "total": round(self.total, MONEY_PLACES),
            "prompt": round(self.prompt, MONEY_PLACES),
            "completion": round(self.completion, MONEY_PLACES),
            "budget": self.budget,
            "budget_remaining": None if remaining is None else round(remaining, MONEY_PLACES),
            "budget_exceeded": self.exhausted,
        }


def build_tracker(tasks: Iterable[TaskConfig]) -> CostTracker:
    """The run's tracker: cost reporting on if any task prices its calls.

    When several tasks declare a budget the smallest one binds, so no task
    can spend past the limit it was given.
    """
    costs = [task.cost for task in tasks if task.cost is not None]
    budgets = [cost.budget for cost in costs if cost.budget is not None]
    return CostTracker(min(budgets, default=None), enabled=bool(costs))
