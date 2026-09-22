"""Memory-bounded global sort: buffer, spill sorted runs, then merge them."""

from __future__ import annotations

import functools
import heapq
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, NamedTuple

from csvmerge.records import Record

# Measured cost of one buffered cell or key part beyond its own characters:
# the string header, the tuples holding it, and the list slot pointing at it.
_ELEMENT_OVERHEAD_BYTES = 96
# Runs merged at once. Each costs an open file and a buffered record, so deep
# run counts are collapsed in earlier passes rather than opened all at once.
_MAX_MERGE_FANIN = 64


@dataclass(frozen=True)
class SortKey:
    """Composite key comparison where a null ranks below every real value.

    That ranking is what ``--desc`` inverts along with everything else, so
    nulls lead an ascending result and trail a descending one.
    """

    values: tuple
    descending: bool

    def __lt__(self, other: "SortKey") -> bool:
        for mine, theirs in zip(self.values, other.values):
            if mine == theirs:
                continue
            ascends = _precedes(mine, theirs)
            return not ascends if self.descending else ascends
        return False


def _precedes(mine, theirs) -> bool:
    """Ascending comparison of two unequal key values, nulls ranking lowest."""
    if mine is None:
        return True
    if theirs is None:
        return False
    return mine < theirs


def sorted_records(
    records: Iterable[Record], descending: bool, budget_bytes: int, temp_dir: str
) -> Iterator[Record]:
    """Yield records in partition and key order, spilling once the buffer is full.

    Everything that fits within ``budget_bytes`` is sorted in memory; anything
    larger leaves sorted runs behind on disk and is streamed back through a
    k-way merge, so peak memory stays bounded by the budget plus one buffered
    record per run.
    """
    order = functools.partial(_order_of, descending=descending)
    store = _RunStore(Path(temp_dir))
    buffer: list[Record] = []
    buffered_bytes = 0
    for record in records:
        buffer.append(record)
        buffered_bytes += _footprint(record)
        if buffered_bytes >= budget_bytes:
            buffer.sort(key=order)
            store.write(buffer, len(buffer))
            buffer, buffered_bytes = [], 0

    buffer.sort(key=order)
    if not store.runs:
        yield from buffer
        return
    streams = [_read_run(run) for run in store.collapse(order)]
    if buffer:
        streams.append(iter(buffer))
    yield from heapq.merge(*streams, key=order)


def _order_of(record: Record, descending: bool) -> tuple:
    """Order by partition first, so each partition's rows arrive as one run.

    The partition prefix only groups; ``--desc`` inverts the sort key alone,
    which is what makes every partition directory sorted in its own right.
    """
    return (record.partition, SortKey(record.key, descending), record.sequence)


def _footprint(record: Record) -> int:
    payload = sum(map(len, record.cells)) + len(record.partition)
    return payload + _ELEMENT_OVERHEAD_BYTES * (len(record.cells) + len(record.key))


class _Run(NamedTuple):
    """A sorted run on disk and how many records it holds."""

    path: Path
    count: int


class _RunStore:
    """The sorted runs spilled so far, kept few enough to merge in one pass."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._written = 0
        self.runs: list[_Run] = []

    def write(self, records: Iterable[Record], count: int) -> None:
        # Names never repeat: a collapse pass writes its result while the runs
        # it is consuming are still on disk.
        self._written += 1
        path = self._directory / f"run-{self._written:05d}.pickle"
        with path.open("wb") as handle:
            for record in records:
                pickle.dump(record, handle, pickle.HIGHEST_PROTOCOL)
        self.runs.append(_Run(path, count))

    def collapse(self, order: Callable[[Record], tuple]) -> list[_Run]:
        """Merge runs in passes until the remaining ones fit the fan-in limit.

        One slot is reserved for the records still held in memory, which join
        the final merge as a stream of their own.
        """
        while len(self.runs) >= _MAX_MERGE_FANIN:
            group, self.runs = self.runs[:_MAX_MERGE_FANIN], self.runs[_MAX_MERGE_FANIN:]
            merged = heapq.merge(*(_read_run(run) for run in group), key=order)
            self.write(merged, sum(run.count for run in group))
            for run in group:
                run.path.unlink()
        return self.runs


def _read_run(run: _Run) -> Iterator[Record]:
    with run.path.open("rb") as handle:
        for _ in range(run.count):
            yield pickle.load(handle)
