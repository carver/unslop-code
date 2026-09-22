"""Progress reporting to stderr while a run is in flight."""

import sys
import time
from typing import Sequence

from accounting import CallStats, CostTracker
from results import Outcome

#: Longest gap between two updates.
INTERVAL_SECONDS = 5.0
#: Share of the run's rows that finishing forces an update, whichever comes first.
ROW_FRACTION = 0.1
SECONDS_PER_MINUTE = 60.0


class Progress:
    """Counts finished rows and prints a paced one-line status to stderr.

    An update is printed every :data:`INTERVAL_SECONDS` or every
    :data:`ROW_FRACTION` of the run's rows, whichever comes first. The
    pass/fail and spend fields appear only when the run has an evaluation and
    priced calls to report. A disabled reporter counts but prints nothing.
    """

    def __init__(
        self,
        total: int,
        stats: Sequence[CallStats],
        tracker: CostTracker,
        *,
        enabled: bool,
        evaluated: bool,
    ) -> None:
        self._total = total
        self._stats = stats
        self._tracker = tracker
        self._enabled = enabled
        self._evaluated = evaluated
        self._step = max(1, round(total * ROW_FRACTION))
        self._started = time.monotonic()
        self._reported_at = self._started
        self._done = 0
        self._passed = 0

    def count_row(self, outcome: Outcome) -> None:
        """Record one finished row, printing an update when one is due."""
        self._done += 1
        self._passed += 1 if outcome.succeeded else 0
        if self._enabled and self._due():
            self._report()

    def _due(self) -> bool:
        if self._done == self._total or self._done % self._step == 0:
            return True
        return time.monotonic() - self._reported_at >= INTERVAL_SECONDS

    def _report(self) -> None:
        self._reported_at = time.monotonic()
        elapsed = self._reported_at - self._started
        percent = round(self._done / self._total * 100) if self._total else 100
        fields = [f"[{self._done}/{self._total}] {percent}% complete"]
        if self._evaluated:
            fields.append(f"{self._passed} passed, {self._done - self._passed} failed")
        fields.append(f"{self._requests_per_minute(elapsed):.1f} rpm")
        if self._tracker.enabled:
            fields.append(f"${self._tracker.total:.2f} spent")
        fields.append(f"ETA: {self._eta_seconds(elapsed)}s")
        print(" | ".join(fields), file=sys.stderr, flush=True)

    def _requests_per_minute(self, elapsed: float) -> float:
        calls = sum(stats.api_calls for stats in self._stats)
        return calls / elapsed * SECONDS_PER_MINUTE if elapsed > 0 else 0.0

    def _eta_seconds(self, elapsed: float) -> int:
        """Seconds left at the pace so far, rounded to whole seconds."""
        if self._done == 0:
            return 0
        return round((self._total - self._done) * elapsed / self._done)
