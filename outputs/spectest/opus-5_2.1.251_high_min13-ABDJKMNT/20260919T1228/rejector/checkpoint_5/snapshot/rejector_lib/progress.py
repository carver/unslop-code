"""`--progress`: a periodic one-line status report on stderr."""

from __future__ import annotations

import asyncio
import sys
import time

INTERVAL_SECONDS = 5.0
STEP_FRACTION = 0.1
TICK_SECONDS = 0.5


class ProgressReporter:
    """Counts finished rows and prints the run's progress as it goes.

    A line is printed whenever another tenth of the inputs is done or five
    seconds have passed since the last one, whichever happens first.
    """

    def __init__(
        self,
        total: int,
        client,
        cost,
        *,
        enabled: bool,
        show_counts: bool,
        stream=sys.stderr,
    ):
        self.total = total
        self._client = client
        self._cost = cost
        self._enabled = enabled
        self._show_counts = show_counts
        self._stream = stream
        self._started = time.monotonic()
        self._reported_at = self._started
        self._reported = 0
        self.completed = 0
        self.passed = 0
        self.failed = 0

    def row_done(self, passed: bool) -> None:
        """Record one finished row, reporting if it crosses a step boundary."""
        self.completed += 1
        self.passed += bool(passed)
        self.failed += not passed
        if self.completed - self._reported >= self._step:
            self._emit()

    async def tick(self) -> None:
        """Report on the clock while the run is in progress."""
        while self._enabled:
            await asyncio.sleep(TICK_SECONDS)
            if time.monotonic() - self._reported_at >= INTERVAL_SECONDS:
                self._emit()

    @property
    def _step(self) -> int:
        return max(1, round(self.total * STEP_FRACTION))

    def _emit(self) -> None:
        self._reported = self.completed
        self._reported_at = time.monotonic()
        if self._enabled:
            print(self._line(), file=self._stream, flush=True)

    def _line(self) -> str:
        """The progress line, with the fields this run has data for."""
        percent = round(self.completed / self.total * 100) if self.total else 100
        parts = [f"[{self.completed}/{self.total}] {percent}% complete"]
        if self._show_counts:
            parts.append(f"{self.passed} passed, {self.failed} failed")
        parts.append(f"{self._rpm:.1f} rpm")
        if self._cost.enabled:
            parts.append(f"${self._cost.total:.2f} spent")
        parts.append(f"ETA: {self._eta}s")
        return " | ".join(parts)

    @property
    def _elapsed(self) -> float:
        return time.monotonic() - self._started

    @property
    def _rpm(self) -> float:
        """Requests per minute achieved so far, across every task."""
        return self._client.usage.calls / self._elapsed * 60 if self._elapsed else 0.0

    @property
    def _eta(self) -> int:
        """Seconds left, at the rate rows have been finishing."""
        if not self.completed:
            return 0
        return round((self.total - self.completed) * self._elapsed / self.completed)
