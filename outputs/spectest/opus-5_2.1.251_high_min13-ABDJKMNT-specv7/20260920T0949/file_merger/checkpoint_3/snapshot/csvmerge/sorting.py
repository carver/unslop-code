"""Stable global ordering with an external merge sort.

Rows are buffered until they reach the memory budget, then each full buffer is
sorted and spilled to a temporary run file as JSON lines. The runs are finally
merged back in a single streaming pass, so peak memory stays proportional to
the budget rather than to the input size.
"""

from __future__ import annotations

import heapq
import json
import tempfile
from operator import itemgetter
from pathlib import Path

#: Half of the announced limit is spent on buffered rows; the rest covers the
#: interpreter, the CSV read buffers and the run streams open during the merge.
_BUDGET_SHARE = 2
_MIN_BUDGET_BYTES = 64 * 1024

#: Rough sizes of the objects a buffered row is made of, used to charge a row
#: for more than just the text it carries.
_BYTES_PER_CELL = 64
_BYTES_PER_KEY_PART = 200
_BYTES_PER_ROW = 200


def budget_bytes(memory_limit_mb: int) -> int:
    """Translate ``--memory-limit-mb`` into a budget for buffered rows."""
    return max(_MIN_BUDGET_BYTES, memory_limit_mb * 1024 * 1024 // _BUDGET_SHARE)


def _row_footprint(parts, cells) -> int:
    """Approximate the memory one buffered row and its sort key occupy.

    A key part is a projected value or a partition segment, so it is measured
    through its text rather than by assuming a shape.
    """
    text = sum(map(len, cells)) + sum(len(str(part)) for part in parts)
    return text + _BYTES_PER_CELL * len(cells) + _BYTES_PER_KEY_PART * len(parts) + _BYTES_PER_ROW


class SortKey:
    """Orders rows by their key parts, then by input appearance.

    ``--desc`` flips the comparison of the key parts only: the sequence number
    stays ascending so that rows with equal keys keep their input order.
    """

    __slots__ = ("parts", "seq", "descending")

    def __init__(self, parts, seq: int, descending: bool):
        self.parts = parts
        self.seq = seq
        self.descending = descending

    def __lt__(self, other: "SortKey") -> bool:
        if self.parts == other.parts:
            return self.seq < other.seq
        return self.parts > other.parts if self.descending else self.parts < other.parts


def sort_rows(rows, descending: bool, budget: int, temp_dir: str | None):
    """Yield the ``(key_parts, cells)`` pairs of ``rows`` in sorted order.

    The key parts travel with the sorted row because a partitioned run reads
    the row's directory segments back out of them.
    """
    with tempfile.TemporaryDirectory(dir=temp_dir, prefix="merge-files-") as scratch:
        buffer = []
        buffered_bytes = 0
        runs = []
        for seq, (parts, cells) in enumerate(rows):
            buffer.append((SortKey(parts, seq, descending), cells))
            buffered_bytes += _row_footprint(parts, cells)
            if buffered_bytes >= budget:
                runs.append(_spill(buffer, Path(scratch) / f"run-{len(runs)}.jsonl"))
                buffer.clear()
                buffered_bytes = 0

        if not runs:
            buffer.sort(key=itemgetter(0))
            yield from ((key.parts, cells) for key, cells in buffer)
            return

        runs.append(_spill(buffer, Path(scratch) / f"run-{len(runs)}.jsonl"))
        streams = [_read_run(path, descending) for path in runs]
        for key, cells in heapq.merge(*streams, key=itemgetter(0)):
            yield key.parts, cells


def _spill(buffer, path: Path) -> Path:
    """Sort the buffer and write it out as one run file."""
    buffer.sort(key=itemgetter(0))
    with open(path, "w", encoding="utf-8") as handle:
        for key, cells in buffer:
            handle.write(json.dumps([key.parts, key.seq, cells]) + "\n")
    return path


def _read_run(path: Path, descending: bool):
    """Replay one run file as ``(SortKey, cells)`` pairs."""
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts, seq, cells = json.loads(line)
            yield SortKey(parts, seq, descending), cells
