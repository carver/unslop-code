"""Progress reporting for a running job, printed to stderr."""

from __future__ import annotations

import sys
import time
from typing import Iterable

from cost import Ledger

# A line is printed at least this often, and at every tenth of the rows.
INTERVAL_SECONDS = 5.0
ROWS_PER_UPDATE = 10


class Progress:
    """Counts what a run has finished and prints a line as it goes.

    Every task of a run shares one reporter, so the line covers the whole run:
    its rows, the requests behind them and what they cost. A reporter that was
    not asked for keeps the counts and prints nothing.
    """

    def __init__(
        self, total: int, evaluated: bool, ledgers: Iterable[Ledger], enabled: bool
    ) -> None:
        self._total = total
        self._evaluated = evaluated
        self._ledgers = list(ledgers)
        self._enabled = enabled
        self._step = max(1, total // ROWS_PER_UPDATE)
        self._started = time.monotonic()
        self._printed_at = self._started
        self._printed = 0
        self._done = 0
        self._passed = 0
        self._calls = 0

    def request(self) -> None:
        """Count one API request, which paces the reported request rate."""
        self._calls += 1

    def row(self, passed: bool) -> None:
        """Count one finished row and print a line when one is due."""
        self._done += 1
        self._passed += passed
        now = time.monotonic()
        if self._done - self._printed >= self._step or now - self._printed_at >= INTERVAL_SECONDS:
            self._printed, self._printed_at = self._done, now
            self._print(now)

    def _print(self, now: float) -> None:
        if not self._enabled:
            return
        elapsed = now - self._started
        fields = [f"{round(self._done / self._total * 100)}% complete"]
        if self._evaluated:
            fields.append(f"{self._passed} passed, {self._done - self._passed} failed")
        fields.append(f"{self._calls / elapsed * 60:.1f} rpm" if elapsed else "0.0 rpm")
        spent = self._spent()
        if spent is not None:
            fields.append(f"${spent:.2f} spent")
        fields.append(f"ETA: {self._eta(elapsed)}s")
        print(f"[{self._done}/{self._total}] {' | '.join(fields)}", file=sys.stderr)

    def _spent(self) -> float | None:
        """What the run has spent so far, or None when no task tracks cost."""
        tracked = [ledger.total for ledger in self._ledgers if ledger.cost is not None]
        return sum(tracked) if tracked else None

    def _eta(self, elapsed: float) -> int:
        """Seconds left at the pace the finished rows set."""
        return round((self._total - self._done) * elapsed / self._done)
