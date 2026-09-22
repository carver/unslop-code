"""What a run spent: request counters, token costs, and the optional spend budget."""

from dataclasses import dataclass, field
from typing import Any, Iterable

from config import CostConfig

#: Decimal places costs are reported to.
COST_PRECISION = 4
#: Tokens one unit of the configured per-1k prices buys.
TOKENS_PER_PRICED_UNIT = 1000


def round_cost(amount: float) -> float:
    """Round a money amount to the precision costs are reported at."""
    return round(amount, COST_PRECISION)


@dataclass
class CallStats:
    """HTTP-level counters shared by every call a client makes."""

    api_calls: int = 0
    first_request_at: float | None = None
    last_response_at: float | None = None

    def record(self, started_at: float, finished_at: float) -> None:
        """Count one HTTP request and widen the observed first-request/last-response window."""
        self.api_calls += 1
        self._widen(started_at, finished_at)

    def merge(self, other: "CallStats") -> None:
        """Fold another task's counters and timing window into this one."""
        self.api_calls += other.api_calls
        if other.first_request_at is not None:
            self._widen(other.first_request_at, other.last_response_at)

    def _widen(self, started_at: float, finished_at: float) -> None:
        if self.first_request_at is None:
            self.first_request_at = started_at
            self.last_response_at = finished_at
            return
        self.first_request_at = min(self.first_request_at, started_at)
        self.last_response_at = max(self.last_response_at, finished_at)

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock seconds from the first request to the last response."""
        if self.first_request_at is None:
            return 0.0
        return self.last_response_at - self.first_request_at


class CostTracker:
    """The spend of every task in a run, and whether the run's budget is used up.

    The budget is a run-wide cap: once the total reaches it no further row is
    started, which leaves ``budget_exceeded`` true in the reported summary. A
    run whose tasks configure different budgets is held to the smallest of
    them, since the cap covers the run as a whole.
    """

    def __init__(self, costs: Iterable[CostConfig | None]) -> None:
        priced = [cost for cost in costs if cost is not None]
        budgets = [cost.budget for cost in priced if cost.budget is not None]
        self._budget = min(budgets) if budgets else None
        self._priced = bool(priced)
        self.prompt = 0.0
        self.completion = 0.0

    def record(self, cost: CostConfig | None, prompt_tokens: int, completion_tokens: int) -> None:
        """Charge one API call at its task's prices."""
        if cost is None:
            return
        self.prompt += prompt_tokens / TOKENS_PER_PRICED_UNIT * cost.prompt_per_1k
        self.completion += completion_tokens / TOKENS_PER_PRICED_UNIT * cost.completion_per_1k

    @property
    def total(self) -> float:
        return self.prompt + self.completion

    @property
    def enabled(self) -> bool:
        """True when at least one task priced its calls, so a cost is worth reporting."""
        return self._priced

    @property
    def exhausted(self) -> bool:
        """True once the run has spent its whole budget, if it was given one."""
        return self._budget is not None and self.total >= self._budget

    def to_json(self) -> dict[str, Any]:
        """The summary's ``cost`` object, including the budget only when there is one."""
        payload = {
            "total": round_cost(self.total),
            "prompt": round_cost(self.prompt),
            "completion": round_cost(self.completion),
        }
        if self._budget is not None:
            payload["budget"] = self._budget
            payload["budget_remaining"] = round_cost(self._budget - self.total)
            payload["budget_exceeded"] = self.exhausted
        return payload


@dataclass
class Meter:
    """One task's view of the run's accounting, updated as its calls return."""

    cost: CostConfig | None
    tracker: CostTracker
    stats: CallStats = field(default_factory=CallStats)

    def count_request(self, started_at: float, finished_at: float) -> None:
        """Count one HTTP request, whatever it returned."""
        self.stats.record(started_at, finished_at)

    def charge(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Charge the tokens a successful response reported against the run's budget."""
        self.tracker.record(self.cost, prompt_tokens, completion_tokens)
