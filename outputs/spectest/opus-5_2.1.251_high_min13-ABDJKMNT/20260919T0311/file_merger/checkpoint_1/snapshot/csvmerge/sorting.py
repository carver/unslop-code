"""External merge sort: buffer records, spill sorted runs, then merge them.

Records are `[sort key, sequence number, output row]`. The sequence number is
the row's position in the input stream, so it both keeps the sort stable and
survives the round trip through a spill file.
"""
from __future__ import annotations

import heapq
import json
import os
from typing import Iterable, Iterator, Sequence

#: Most runs merged at once; caps open files and read buffers during a merge.
_MAX_MERGE_FANIN = 64

#: Rough per-record allowance for Python object overhead beyond the cell text.
_RECORD_OVERHEAD_BYTES = 256


class _Ordering:
    """Sort position of one record: key first, then input appearance.

    `--desc` inverts the key comparison only; ties still resolve in input order,
    which is what keeps a descending sort stable.
    """

    __slots__ = ("key", "sequence", "descending")

    def __init__(self, key: Sequence, sequence: int, descending: bool):
        self.key = key
        self.sequence = sequence
        self.descending = descending

    def __lt__(self, other: "_Ordering") -> bool:
        if self.key != other.key:
            return self.key > other.key if self.descending else self.key < other.key
        return self.sequence < other.sequence


class ExternalSorter:
    """Sorts an unbounded record stream within a fixed buffer budget."""

    def __init__(self, spill_dir: str, budget_bytes: int, descending: bool):
        self._spill_dir = spill_dir
        self._budget_bytes = budget_bytes
        self._descending = descending
        self._buffer: list[list] = []
        self._buffered_bytes = 0
        self._runs: list[str] = []
        self._next_run = 0
        self._count = 0

    def add(self, key: Sequence, row: Sequence[str]) -> None:
        """Accept one row, spilling the buffer to disk once it exceeds the budget."""
        self._buffer.append([key, self._count, row])
        self._count += 1
        self._buffered_bytes += sum(map(len, row)) + _RECORD_OVERHEAD_BYTES
        if self._buffered_bytes > self._budget_bytes:
            self._spill()

    def merged(self) -> Iterator[Sequence[str]]:
        """Yield every row in sort order, collapsing runs first if there are many."""
        while len(self._runs) > _MAX_MERGE_FANIN:
            self._collapse_runs()
        sources = [_read_run(path) for path in self._runs]
        sources.append(self._sorted_buffer())
        for record in heapq.merge(*sources, key=self._ordering_of):
            yield record[2]

    def _ordering_of(self, record: list) -> _Ordering:
        return _Ordering(record[0], record[1], self._descending)

    def _sorted_buffer(self) -> list[list]:
        return sorted(self._buffer, key=self._ordering_of)

    def _spill(self) -> None:
        """Move the buffer to a sorted run on disk."""
        self._runs.append(self._write_run(self._sorted_buffer()))
        self._buffer.clear()
        self._buffered_bytes = 0

    def _collapse_runs(self) -> None:
        """Merge runs in groups, so the final merge holds few files open at once."""
        collapsed = []
        for start in range(0, len(self._runs), _MAX_MERGE_FANIN):
            group = self._runs[start:start + _MAX_MERGE_FANIN]
            sources = [_read_run(path) for path in group]
            collapsed.append(self._write_run(heapq.merge(*sources, key=self._ordering_of)))
            for path in group:
                os.remove(path)
        self._runs = collapsed

    def _write_run(self, records: Iterable[list]) -> str:
        """Write already-ordered records to a new run file and return its path."""
        path = os.path.join(self._spill_dir, f"run-{self._next_run:06d}.jsonl")
        self._next_run += 1
        with open(path, "w", encoding="utf-8") as handle:
            handle.writelines(
                json.dumps(record, separators=(",", ":")) + "\n" for record in records
            )
        return path


def _read_run(path: str) -> Iterator[list]:
    """Stream one sorted run back, one record per line."""
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)
