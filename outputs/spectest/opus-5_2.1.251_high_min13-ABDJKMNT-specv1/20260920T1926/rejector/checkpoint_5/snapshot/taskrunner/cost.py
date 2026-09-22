"""Cost accounting and the budget that can halt a run.

Prices are per task, but the running total and the budget are run-wide: every
generation, judge and agentic call is charged to one shared tracker, and the
run stops dispatching as soon as that total reaches the budget.
"""

from __future__ import annotations

from typing import Any, Iterable

from .config import CostConfig, TaskConfig

# Costs are reported with more precision than the spec's four-decimal floor so
# that per-call charges of a fraction of a cent stay visible.
COST_PLACES = 6


class CostTracker:
    """The run's spend so far, and whether it has reached the budget."""

    def __init__(self, budget: float | None) -> None:
        self.budget = budget
        self.prompt = 0.0
        self.completion = 0.0
        self.calls = 0

    def charge(self, prompt_tokens: int, completion_tokens: int, rates: CostConfig) -> None:
        self.prompt += prompt_tokens / 1000 * rates.prompt_cost_per_1k
        self.completion += completion_tokens / 1000 * rates.completion_cost_per_1k

    @property
    def total(self) -> float:
        return self.prompt + self.completion

    @property
    def exhausted(self) -> bool:
        """True once the budget is reached; no further request may be sent."""
        return self.budget is not None and self.total >= self.budget

    def summary(self) -> dict[str, Any]:
        """The summary's `cost` object."""
        total = round(self.total, COST_PLACES)
        return {
            "total": total,
            "prompt": round(self.prompt, COST_PLACES),
            "completion": round(self.completion, COST_PLACES),
            "budget": self.budget,
            "budget_remaining": None if self.budget is None else round(
                self.budget - total, COST_PLACES
            ),
            "budget_exceeded": self.exhausted,
        }


def run_budget(tasks: Iterable[TaskConfig]) -> float | None:
    """The binding budget across the run: the lowest any task configures."""
    budgets = [task.cost.budget for task in tasks if task.cost and task.cost.budget is not None]
    return min(budgets) if budgets else None


def is_priced(tasks: Iterable[TaskConfig]) -> bool:
    """Whether any selected task configures cost, which the summary reports."""
    return any(task.cost is not None for task in tasks)
