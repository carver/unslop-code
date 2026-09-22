"""Cost accounting: per-call charges, the run-wide ledger, and the budget."""

from __future__ import annotations

from dataclasses import dataclass

#: "report them to at least four decimal places": rounding here only removes
#: floating-point noise, it never hides a cost a fixture would expect (T76).
PRECISION = 6


@dataclass(frozen=True)
class CostConfig:
    """One task's price list, and the budget the run may spend."""

    prompt_cost_per_1k: float = 0.0
    completion_cost_per_1k: float = 0.0
    budget: float | None = None

    def prompt_cost(self, tokens: float) -> float:
        """``prompt_tokens / 1000 * prompt_cost_per_1k``."""
        return tokens / 1000 * self.prompt_cost_per_1k

    def completion_cost(self, tokens: float) -> float:
        """``completion_tokens / 1000 * completion_cost_per_1k``."""
        return tokens / 1000 * self.completion_cost_per_1k


#: The rates of a task that configures none: charging it costs nothing.
FREE = CostConfig()


@dataclass
class Ledger:
    """Running cost of the whole run, shared by every task (T74).

    ``tracked`` says whether any task configured cost at all; when it did not,
    the summary omits its `cost` field. ``budget`` is the binding budget across
    the running tasks, or ``None`` when no task set one.
    """

    tracked: bool = False
    budget: float | None = None
    prompt: float = 0.0
    completion: float = 0.0

    def charge(self, prompt_tokens: int, completion_tokens: int, rates: CostConfig) -> None:
        """Bill one API response against the task's rates."""
        self.prompt += rates.prompt_cost(prompt_tokens)
        self.completion += rates.completion_cost(completion_tokens)

    @property
    def total(self) -> float:
        return self.prompt + self.completion

    @property
    def exhausted(self) -> bool:
        """Whether the budget has been reached; no new request may be sent."""
        return self.budget is not None and self.total >= self.budget

    def summary(self) -> dict:
        """The summary's `cost` object."""
        remaining = None if self.budget is None else round(self.budget - self.total, PRECISION)
        return {
            "total": round(self.total, PRECISION),
            "prompt": round(self.prompt, PRECISION),
            "completion": round(self.completion, PRECISION),
            "budget": self.budget,
            "budget_remaining": remaining,
            "budget_exceeded": self.exhausted,
        }


def build_ledger(costs) -> Ledger:
    """The run's ledger: tracked when any task prices its calls, with the
    smallest configured budget as the one that stops the run (T74)."""
    configured = [cost for cost in costs if cost is not None]
    budgets = [cost.budget for cost in configured if cost.budget is not None]
    return Ledger(tracked=bool(configured), budget=min(budgets) if budgets else None)
