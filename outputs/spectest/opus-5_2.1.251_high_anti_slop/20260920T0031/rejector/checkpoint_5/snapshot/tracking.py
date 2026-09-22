"""Run-wide measurement: the span requests cover, how many were made, and progress.

Every task of a run feeds the same `RunMetrics`, so the summary and the optional
`--progress` line describe the run as a whole rather than one task at a time.
"""

from __future__ import annotations

import sys
import time

from cost import CostTracker
from rows import Result, row_passed

#: Seconds between progress lines when the row count has not moved far enough on its own.
REPORT_SECONDS = 5.0
#: Fraction of the run's rows that also triggers a progress line.
REPORT_EVERY = 10


class Timeline:
    """The span a run's requests cover, shared by every client taking part in it."""

    def __init__(self) -> None:
        self.first_request_at: float | None = None
        self.last_response_at = 0.0

    def started(self) -> float:
        """Record and return the instant a request goes out."""
        now = time.monotonic()
        if self.first_request_at is None:
            self.first_request_at = now
        return now

    def finished(self) -> float:
        """Record and return the instant a response comes back."""
        self.last_response_at = time.monotonic()
        return self.last_response_at

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock seconds from the first request sent to the last response received."""
        if self.first_request_at is None:
            return 0.0
        return self.last_response_at - self.first_request_at


class RunMetrics:
    """The counters every request feeds, whichever task made it."""

    def __init__(self, cost: CostTracker) -> None:
        self.timeline = Timeline()
        self.cost = cost
        self.api_calls = 0

    def request(self) -> float:
        """Record a request going out and return the instant it did."""
        self.api_calls += 1
        return self.timeline.started()

    @property
    def throughput_rpm(self) -> float:
        """Requests per minute observed so far."""
        elapsed = self.timeline.elapsed_seconds
        return self.api_calls / elapsed * 60 if elapsed else 0.0


class Progress:
    """Prints a one-line stderr update as rows finish.

    A line goes out every `REPORT_SECONDS` or every tenth of the run, whichever
    comes first, and once more when the last row lands.
    """

    def __init__(self, total: int, *, evaluated: bool) -> None:
        self.total = total
        self.done = 0
        self.passed = 0
        self.failed = 0
        self._evaluated = evaluated
        self._started = time.monotonic()
        self._step = max(1, total // REPORT_EVERY)
        self._due_at = self._started + REPORT_SECONDS
        self._due_after = self._step

    def row(self, result: Result, metrics: RunMetrics) -> None:
        """Count one finished row, reporting when a time or row milestone has passed."""
        self.done += 1
        passed = row_passed(result)
        self.passed += passed
        self.failed += not passed
        if self.done >= self._due_after or time.monotonic() >= self._due_at or self.done == self.total:
            self._report(metrics)

    def _report(self, metrics: RunMetrics) -> None:
        elapsed = time.monotonic() - self._started
        eta = (self.total - self.done) * elapsed / self.done
        fields = [f"[{self.done}/{self.total}] {round(self.done / self.total * 100)}% complete"]
        if self._evaluated:
            fields.append(f"{self.passed} passed, {self.failed} failed")
        fields.append(f"{metrics.throughput_rpm:.1f} rpm")
        if metrics.cost.configured:
            fields.append(f"${metrics.cost.total:.2f} spent")
        fields.append(f"ETA: {round(eta)}s")

        print(" | ".join(fields), file=sys.stderr)
        self._due_at = time.monotonic() + REPORT_SECONDS
        self._due_after = self.done + self._step

