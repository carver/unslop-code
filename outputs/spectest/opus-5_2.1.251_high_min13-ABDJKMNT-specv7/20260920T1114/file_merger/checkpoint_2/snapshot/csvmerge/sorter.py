"""A stable external sort: sorted chunks spill to disk and are merged back.

Rows are buffered until they reach the memory budget, then written to a temporary
file as sorted JSON lines. The final pass merges the spills, so peak memory stays
proportional to the budget rather than to the input size.

Both phases inherit Python's sort stability, including with ``reverse=True``:
equal keys keep the order they were added in, and ties between spills resolve in
favour of the older spill.
"""

from __future__ import annotations

import heapq
import json
from contextlib import ExitStack
from operator import itemgetter
from pathlib import Path
from typing import Iterator

# Rough per-row cost of the Python objects wrapping the cell text.
_ROW_OVERHEAD_BYTES = 128

_key_of = itemgetter(0)


class ExternalSorter:
    """Collects rows, then replays them in key order."""

    def __init__(self, temp_dir: Path, memory_limit_bytes: int, descending: bool):
        self._temp_dir = temp_dir
        self._limit = memory_limit_bytes
        self._descending = descending
        self._buffer: list[tuple[list, list[str]]] = []
        self._buffered_bytes = 0
        self._spills: list[Path] = []

    def add(self, key: list, cells: list[str]) -> None:
        """Queue one output row, spilling the buffer once it outgrows the budget."""
        self._buffer.append((key, cells))
        self._buffered_bytes += sum(map(len, cells)) + _ROW_OVERHEAD_BYTES
        if self._buffered_bytes >= self._limit:
            self._spill()

    def sorted_rows(self) -> Iterator[list[str]]:
        """Yield every row's cells in key order."""
        if not self._spills:
            yield from (cells for _, cells in self._sorted_buffer())
            return
        self._spill()
        with ExitStack() as stack:
            streams = [
                map(json.loads, stack.enter_context(open(path, encoding="utf-8")))
                for path in self._spills
            ]
            merged = heapq.merge(*streams, key=_key_of, reverse=self._descending)
            yield from (cells for _, cells in merged)

    def _sorted_buffer(self) -> list[tuple[list, list[str]]]:
        return sorted(self._buffer, key=_key_of, reverse=self._descending)

    def _spill(self) -> None:
        """Write the buffered rows to a new sorted spill file."""
        if not self._buffer:
            return
        path = self._temp_dir / f"chunk-{len(self._spills):05d}.jsonl"
        with open(path, "w", encoding="utf-8") as handle:
            for record in self._sorted_buffer():
                handle.write(json.dumps(record) + "\n")
        self._spills.append(path)
        self._buffer = []
        self._buffered_bytes = 0
