"""Periodic run status on stderr, enabled by `--progress`."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time

from .api import RunStats
from .cost import CostTracker

TICK_SECONDS = 5.0
BOUNDARIES = 10  # one update per 10% of the total


class Progress:
    """Counts finished rows and reports how the run is going.

    A line is printed whenever the run crosses a 10% boundary; a background
    ticker prints one every `TICK_SECONDS` in between, so a slow run still
    reports while its first rows are in flight.
    """

    def __init__(
        self,
        total: int,
        stats: RunStats,
        costs: CostTracker,
        show_results: bool,
        enabled: bool,
    ):
        self._total = total
        self._stats = stats
        self._costs = costs
        self._show_results = show_results
        self._enabled = enabled
        self._done = 0
        self._passed = 0
        self._started = time.monotonic()
        self._last_emit = self._started
        self._last_mark = 0

    def record(self, passed: bool) -> None:
        """Count one finished row, reporting at each 10% boundary it crosses."""
        self._done += 1
        self._passed += bool(passed)

        mark = self._done * BOUNDARIES // self._total if self._total else BOUNDARIES
        if mark > self._last_mark:
            self._last_mark = mark
            self._emit()

    @contextlib.asynccontextmanager
    async def reporting(self):
        """Run the periodic ticker for the lifetime of the block."""
        if not self._enabled:
            yield
            return

        ticker = asyncio.create_task(self._tick())
        try:
            yield
        finally:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(max(0.2, TICK_SECONDS - (time.monotonic() - self._last_emit)))
            if time.monotonic() - self._last_emit >= TICK_SECONDS:
                self._emit()

    def _emit(self) -> None:
        if not self._enabled:
            return
        self._last_emit = time.monotonic()
        print(self._line(), file=sys.stderr, flush=True)

    def _line(self) -> str:
        """The status line: counts, optional results, request rate, ETA."""
        elapsed = max(time.monotonic() - self._started, 1e-9)
        percent = round(self._done / self._total * 100) if self._total else 100

        parts = [f"[{self._done}/{self._total}] {percent}% complete"]
        if self._show_results:
            parts.append(f"{self._passed} passed, {self._done - self._passed} failed")
        parts.append(f"{self._stats.calls / elapsed * 60:.1f} rpm")
        if self._costs.enabled:
            parts.append(f"${self._costs.total:.2f} spent")
        parts.append(f"ETA: {self._eta(elapsed)}s")
        return " | ".join(parts)

    def _eta(self, elapsed: float) -> int:
        """Seconds left at the row rate achieved so far."""
        if self._done == 0:
            return 0
        return round((self._total - self._done) * elapsed / self._done)
