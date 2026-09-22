"""Stable external sort: spill sorted chunks to disk, then merge them.

Rows are sorted by a composite key whose values keep the Python type they were
cast to.  ``rank_value`` turns such a value into a tuple that orders totally
even when a column mixes types (``--on-type-error keep-string`` can leave raw
text in a typed column) and that always sorts nulls lowest, which puts them
first when ascending and last when descending.
"""

from __future__ import annotations

import heapq
import pickle
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator, NamedTuple

#: Fraction of the memory limit a chunk may occupy; the rest covers the
#: interpreter, the CSV buffers and the heap used while merging.
CHUNK_BUDGET_FRACTION = 0.5

#: Rough per-cell cost of a short Python string, on top of its characters.
_CELL_OVERHEAD_BYTES = 64
_ROW_OVERHEAD_BYTES = 256

_NULL_RANK, _NUMBER_RANK, _TEXT_RANK, _DATE_RANK, _TIMESTAMP_RANK = range(5)


class Record(NamedTuple):
    """One output row: its ranked sort key, arrival number and rendered cells."""

    ranked: tuple
    sequence: int
    cells: tuple[str | None, ...]


class _Descending(NamedTuple):
    """Inverts the order of a ranked key, for ``--desc``.

    Equality stays element-wise, so rows with equal keys still fall through to
    their arrival number and the sort remains stable.
    """

    ranked: tuple

    def __lt__(self, other: "_Descending") -> bool:
        return other.ranked < self.ranked


def rank_value(value: object) -> tuple[int, object]:
    """Pair a key value with a type rank so unlike types still compare."""
    if value is None:
        return (_NULL_RANK, 0)
    if isinstance(value, (bool, int, float)):
        return (_NUMBER_RANK, value)
    if isinstance(value, str):
        return (_TEXT_RANK, value)
    if isinstance(value, datetime):
        return (_TIMESTAMP_RANK, value)
    return (_DATE_RANK, value)


def make_sort_key(descending: bool) -> Callable[[Record], tuple]:
    """Build the ``key`` function used both in memory and while merging."""
    if descending:
        return lambda record: (_Descending(record.ranked), record.sequence)
    return lambda record: (record.ranked, record.sequence)


def estimate_size(record: Record) -> int:
    """Approximate the memory a record occupies, for chunk accounting."""
    cells = sum(len(cell) + _CELL_OVERHEAD_BYTES for cell in record.cells if cell)
    return cells + _ROW_OVERHEAD_BYTES


def external_sort(
    records: Iterable[Record],
    key: Callable[[Record], tuple],
    workdir: Path,
    budget_bytes: int,
) -> Iterator[Record]:
    """Sort a record stream of any size, using at most ``budget_bytes`` per chunk.

    Chunks are sorted in memory and written to ``workdir``; the returned
    iterator merges them lazily.  Inputs that fit in the budget never touch
    disk.
    """
    chunk: list[Record] = []
    chunk_bytes = 0
    spilled: list[Path] = []
    for record in records:
        chunk.append(record)
        chunk_bytes += estimate_size(record)
        if chunk_bytes >= budget_bytes:
            spilled.append(_spill(chunk, key, workdir / f"chunk-{len(spilled):05d}"))
            chunk, chunk_bytes = [], 0
    if not spilled:
        chunk.sort(key=key)
        return iter(chunk)
    if chunk:
        spilled.append(_spill(chunk, key, workdir / f"chunk-{len(spilled):05d}"))
    return heapq.merge(*(_replay(path) for path in spilled), key=key)


def _spill(chunk: list[Record], key: Callable[[Record], tuple], path: Path) -> Path:
    """Sort a chunk and write it to ``path`` as a stream of pickled records."""
    chunk.sort(key=key)
    with path.open("wb") as handle:
        for record in chunk:
            pickle.dump(record, handle, pickle.HIGHEST_PROTOCOL)
    return path


def _replay(path: Path) -> Iterator[Record]:
    """Read back a spilled chunk one record at a time."""
    with path.open("rb") as handle:
        while True:
            try:
                yield pickle.load(handle)
            except EOFError:
                return


def budget_from_limit(memory_limit_mb: int) -> int:
    """Chunk budget, in bytes, derived from the requested memory limit."""
    return max(int(memory_limit_mb * 1024 * 1024 * CHUNK_BUDGET_FRACTION), _ROW_OVERHEAD_BYTES)
