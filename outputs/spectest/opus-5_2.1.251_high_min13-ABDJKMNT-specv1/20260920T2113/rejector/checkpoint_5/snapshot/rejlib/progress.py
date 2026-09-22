"""`--progress`: a periodic one-line status on stderr while rows are processed."""

from __future__ import annotations

import asyncio
import sys
import time

from rejlib.api import Stats
from rejlib.cost import Ledger
from rejlib.rows import counts_as_passed

#: "every 5 seconds or every 10% of total inputs, whichever comes first"
INTERVAL = 5.0
STEP_FRACTION = 0.1


class Progress:
    """Counts finished rows and reports how the run is going.

    ``evaluated`` and the ledger decide which optional fields the line carries:
    pass/fail counts need an evaluation, the amount spent needs cost tracking.
    """

    def __init__(self, total: int, *, evaluated: bool, ledger: Ledger,
                 stream=sys.stderr):
        self._total = total
        self._evaluated = evaluated
        self._ledger = ledger
        self._stream = stream
        self._stats: list[Stats] = []
        self._started = time.monotonic()
        self._printed = self._started
        self._step = max(1, round(total * STEP_FRACTION))
        self._next_step = self._step
        self._done = 0
        self._passed = 0

    def track(self, stats: Stats) -> None:
        """Include one task's request counters in the reported request rate."""
        self._stats.append(stats)

    def row_done(self, row: dict) -> None:
        """Count one finished output row, reporting on every 10% of the inputs."""
        self._done += 1
        self._passed += counts_as_passed(row)
        if self._done >= self._next_step:
            self._next_step = self._done + self._step
            self._report()

    async def ticker(self) -> None:
        """Report whenever ``INTERVAL`` seconds pass without a line."""
        while True:
            await asyncio.sleep(max(0.1, INTERVAL - (time.monotonic() - self._printed)))
            if time.monotonic() - self._printed >= INTERVAL:
                self._report()

    def _report(self) -> None:
        print(self._line(), file=self._stream, flush=True)
        self._printed = time.monotonic()

    def _line(self) -> str:
        elapsed = time.monotonic() - self._started
        parts = [f"[{self._done}/{self._total}] {self._percent()}% complete"]
        if self._evaluated:
            parts.append(f"{self._passed} passed, {self._done - self._passed} failed")
        parts.append(f"{self._rpm(elapsed):.1f} rpm")
        if self._ledger.tracked:
            parts.append(f"${self._ledger.total:.2f} spent")
        parts.append(f"ETA: {self._eta(elapsed)}s")
        return " | ".join(parts)

    def _percent(self) -> int:
        return round(self._done * 100 / self._total) if self._total else 100

    def _rpm(self, elapsed: float) -> float:
        """Requests per minute observed so far, across every task."""
        calls = sum(stats.api_calls for stats in self._stats)
        return calls / elapsed * 60 if elapsed > 0 else 0.0

    def _eta(self, elapsed: float) -> int:
        """Seconds left at the pace rows have been finishing (T90)."""
        if not self._done:
            return 0
        return round((self._total - self._done) * elapsed / self._done)
