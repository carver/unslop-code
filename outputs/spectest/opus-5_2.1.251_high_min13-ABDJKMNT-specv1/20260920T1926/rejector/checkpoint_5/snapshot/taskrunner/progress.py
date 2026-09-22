"""`--progress`: periodic run status on stderr.

A line is printed whenever five seconds have passed or another tenth of the
run's rows has finished, whichever comes first. Fields the run cannot measure
— evaluation verdicts, cost — are left out rather than shown as zeroes.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import TextIO

from .cost import CostTracker

REPORT_SECONDS = 5.0
REPORT_FRACTION = 0.1
# How often the background ticker checks whether a line is due.
TICK_SECONDS = 0.5


class ProgressReporter:
    """Counts finished rows and prints the run's status when one is due."""

    def __init__(
        self,
        total: int,
        tracker: CostTracker,
        evaluated: bool,
        priced: bool,
        stream: TextIO | None = None,
    ) -> None:
        self.total = total
        self._tracker = tracker
        self._evaluated = evaluated
        self._priced = priced
        self._stream = stream or sys.stderr
        self._started = time.monotonic()
        self._done = 0
        self._passed = 0
        self._reported_at = self._started
        self._reported_rows = 0

    def row_done(self, passed: bool) -> None:
        self._done += 1
        self._passed += passed
        self._report_if_due()

    async def tick(self) -> None:
        """Keep reporting while the run is quiet, until the run cancels it."""
        while True:
            await asyncio.sleep(TICK_SECONDS)
            self._report_if_due()

    def _report_if_due(self) -> None:
        now = time.monotonic()
        every = max(1, round(self.total * REPORT_FRACTION))
        if self._done - self._reported_rows < every and now - self._reported_at < REPORT_SECONDS:
            return
        self._reported_at, self._reported_rows = now, self._done
        print(self._line(now - self._started), file=self._stream, flush=True)

    def _line(self, elapsed: float) -> str:
        percent = round(self._done / self.total * 100) if self.total else 100
        fields = [f"[{self._done}/{self.total}] {percent}% complete"]
        if self._evaluated:
            fields.append(f"{self._passed} passed, {self._done - self._passed} failed")
        fields.append(f"{self._rate(elapsed) * 60:.1f} rpm")
        if self._priced:
            fields.append(f"${self._tracker.total:.2f} spent")
        fields.append(f"ETA: {self._eta(elapsed)}s")
        return " | ".join(fields)

    def _rate(self, elapsed: float) -> float:
        """Requests per second so far."""
        return self._tracker.calls / elapsed if elapsed else 0.0

    def _eta(self, elapsed: float) -> int:
        """Seconds left at the pace rows have been finishing at."""
        if not self._done or self._done >= self.total:
            return 0
        return round((self.total - self._done) * elapsed / self._done)
