"""Progress updates printed to stderr while a run is in flight."""

from __future__ import annotations

import time
from math import ceil
from typing import Any, TextIO

from client import ClientStats
from cost import CostTracker
from records import is_passed

UPDATE_SECONDS = 5.0
#: Share of the run's rows between updates, when rows finish faster than that.
UPDATE_FRACTION = 0.1


class ProgressReporter:
    """Counts finished rows and reports on them when an update is due.

    An update goes out every `UPDATE_SECONDS`, or every tenth of the run's rows,
    whichever comes first. The verdict and cost fields are only shown when the
    run has something to put in them, and a run started without `--progress`
    passes no stream and so only counts.
    """

    def __init__(
        self,
        total: int,
        stats: list[ClientStats],
        cost: CostTracker,
        verdicts: bool,
        stream: TextIO | None = None,
    ) -> None:
        self._total = total
        self._stats = stats
        self._cost = cost
        self._verdicts = verdicts
        self._stream = stream
        self._step = max(1, ceil(total * UPDATE_FRACTION))
        self._started = time.monotonic()
        self._last_update = self._started
        self._next_row = self._step
        self._done = 0
        self._passed = 0

    def record(self, record: dict[str, Any]) -> None:
        """Count one finished row, reporting if this row is due an update."""
        self._done += 1
        if is_passed(record):
            self._passed += 1
        now = time.monotonic()
        if self._done >= self._next_row or now - self._last_update >= UPDATE_SECONDS:
            self._report(now)

    def _report(self, now: float) -> None:
        self._last_update = now
        self._next_row = self._done + self._step
        if self._stream is None:
            return
        elapsed = now - self._started
        fields = [f"[{self._done}/{self._total}] {round(self._done / self._total * 100)}% complete"]
        if self._verdicts:
            fields.append(f"{self._passed} passed, {self._done - self._passed} failed")
        fields.append(f"{sum(stat.api_calls for stat in self._stats) / elapsed * 60:.1f} rpm")
        if self._cost.configured:
            fields.append(f"${self._cost.total:.2f} spent")
        fields.append(f"ETA: {round((self._total - self._done) * elapsed / self._done)}s")
        print(" | ".join(fields), file=self._stream, flush=True)

