"""Cost accounting: what a run spends on tokens and the budget that stops it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

#: Token prices are quoted per thousand tokens.
TOKENS_PER_UNIT = 1000
#: Decimals kept in the reported figures; enough for cheap runs, short of float noise.
PRECISION = 6


@dataclass(frozen=True)
class CostConfig:
    """What one task's tokens cost, and the budget the run it belongs to may spend."""

    prompt_per_1k: float = 0.0
    completion_per_1k: float = 0.0
    budget: float | None = None

    def of(self, prompt_tokens: int, completion_tokens: int) -> tuple[float, float]:
        """The prompt and completion cost of one API call."""
        return (
            prompt_tokens / TOKENS_PER_UNIT * self.prompt_per_1k,
            completion_tokens / TOKENS_PER_UNIT * self.completion_per_1k,
        )


class CostTracker:
    """The spend of a whole run: every task, judge call and agentic iteration in it."""

    def __init__(self, budget: float | None = None, configured: bool = False) -> None:
        self.budget = budget
        #: Whether any task priced its tokens; an unpriced run reports no cost at all.
        self.configured = configured
        self.prompt = 0.0
        self.completion = 0.0

    @property
    def total(self) -> float:
        return self.prompt + self.completion

    @property
    def exhausted(self) -> bool:
        """Whether the budget is spent, which stops any further request going out."""
        return self.budget is not None and self.total >= self.budget

    def record(self, config: CostConfig | None, prompt_tokens: int, completion_tokens: int) -> None:
        """Bill one API call to the run; a task without prices spends nothing."""
        if config is None:
            return
        prompt, completion = config.of(prompt_tokens, completion_tokens)
        self.prompt += prompt
        self.completion += completion

    def summary(self) -> dict[str, Any] | None:
        """The summary's `cost` object, or None when no task priced its tokens."""
        if not self.configured:
            return None
        return {
            "total": round(self.total, PRECISION),
            "prompt": round(self.prompt, PRECISION),
            "completion": round(self.completion, PRECISION),
            "budget": self.budget,
            "budget_remaining": None if self.budget is None else round(self.budget - self.total, PRECISION),
            "budget_exceeded": self.exhausted,
        }


def build_tracker(configs: Sequence[CostConfig | None]) -> CostTracker:
    """One tracker for the whole run, bounded by the tightest budget any task sets."""
    budgets = [config.budget for config in configs if config is not None and config.budget is not None]
    return CostTracker(budget=min(budgets, default=None), configured=any(config is not None for config in configs))
