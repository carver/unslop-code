"""A bounded-memory sort: sorted runs are spilled to disk and merged back.

Rows are sorted by their partition first and their key second, so that the
rows of one partition leave the sort together and in key order.

Rows are buffered until they fill the memory budget, then written to a
temporary file as a sorted run.  The final pass merges every run, plus
whatever is still buffered, with a k-way merge, so the peak memory stays at
roughly one buffer regardless of how large the inputs are.  Very large inputs
produce more runs than a process should keep open at once, so runs are first
combined in batches until few enough remain for the final merge.
"""

from __future__ import annotations

import heapq
import json
import tempfile
from pathlib import Path
from typing import Iterable, Iterator

from output import OutputRow
from rows import KeyCell, RowKey

# One line of a run: partition segments, key cells, input sequence number and
# output cells.  JSON reads it back as a list of the same four parts.
Run = tuple[list[str], list[KeyCell], int, list[str]]

# How many runs a single merge may read at once, bounding open file handles.
_MAX_MERGE_WIDTH = 64

# Share of the budget the row buffer may use; the rest covers the interpreter
# itself, the CSV reader buffers and the heap used by the final merge.
_BUFFER_SHARE = 0.4
# Rough cost of one buffered cell: a short Python object plus its list slot.
_PER_CELL_OVERHEAD = 128


class ExternalSorter:
    """Collects rows through :meth:`add` and replays them in key order."""

    def __init__(self, descending: bool, memory_limit_bytes: int, temp_dir: Path | None) -> None:
        self._descending = descending
        self._budget = max(int(memory_limit_bytes * _BUFFER_SHARE), _PER_CELL_OVERHEAD)
        self._workspace = tempfile.TemporaryDirectory(prefix="merge_files-", dir=temp_dir)
        self._runs: list[Path] = []
        self._written_runs = 0
        self._buffer: list[Run] = []
        self._buffered_bytes = 0
        self._added = 0

    def __enter__(self) -> "ExternalSorter":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._workspace.cleanup()

    def add(self, partition: list[str], key_cells: list[KeyCell], cells: list[str]) -> None:
        """Buffer one row, spilling a sorted run once the budget is used up."""
        self._buffer.append((partition, key_cells, self._added, cells))
        self._added += 1
        self._buffered_bytes += sum(
            len(cell) for cell in (*cells, *partition)
        ) + _PER_CELL_OVERHEAD * (len(cells) + len(key_cells) + len(partition))
        if self._buffered_bytes >= self._budget:
            self._spill()

    def sorted_rows(self) -> Iterator[OutputRow]:
        """Yield every row added as its partition and its output cells."""
        runs = self._runs
        while len(runs) > _MAX_MERGE_WIDTH:
            runs = self._combine(runs)
        sources = [_read_run(path) for path in runs]
        if self._buffer:
            sources.append(iter(sorted(self._buffer, key=self._key)))
        for partition, _key_cells, _seq, cells in heapq.merge(*sources, key=self._key):
            yield partition, cells

    def _spill(self) -> None:
        self._runs.append(self._write_run(sorted(self._buffer, key=self._key)))
        self._buffer = []
        self._buffered_bytes = 0

    def _combine(self, runs: list[Path]) -> list[Path]:
        """Merge the runs in batches, replacing each batch with a single run."""
        combined = []
        for start in range(0, len(runs), _MAX_MERGE_WIDTH):
            batch = runs[start : start + _MAX_MERGE_WIDTH]
            sources = [_read_run(path) for path in batch]
            combined.append(self._write_run(heapq.merge(*sources, key=self._key)))
            for path in batch:
                path.unlink()
        return combined

    def _write_run(self, rows: Iterable[Run]) -> Path:
        path = Path(self._workspace.name) / f"run-{self._written_runs:06d}.jsonl"
        self._written_runs += 1
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        return path

    def _key(self, run: Run) -> RowKey:
        partition, key_cells, seq, _cells = run
        return RowKey([partition, *key_cells], seq, self._descending)


def _read_run(path: Path) -> Iterator[Run]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)
