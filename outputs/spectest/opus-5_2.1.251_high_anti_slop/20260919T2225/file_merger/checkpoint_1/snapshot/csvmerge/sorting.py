"""Stable external merge sort: bounded in-memory runs spilled to temporary files."""

from __future__ import annotations

import heapq
import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from tempfile import TemporaryDirectory

MEGABYTE = 1024 * 1024

#: Share of the memory budget the run buffer may hold. The rest covers the
#: interpreter, the reader/writer buffers and the heap used while merging.
_BUFFER_FRACTION = 0.5

#: Rough CPython cost of one field: the ``str`` object header plus a list slot.
_FIELD_OVERHEAD_BYTES = 64
_RECORD_OVERHEAD_BYTES = 128


@dataclass
class Record:
    """One output row plus everything needed to order it."""

    keys: list[list]
    seq: int
    row: list[str]


class SortKey:
    """Orders records by key, reversing only the key comparison when descending.

    The input sequence number always breaks ties ascending, which keeps equal
    keys in input order in both directions.
    """

    __slots__ = ("keys", "seq", "descending")

    def __init__(self, record: Record, descending: bool) -> None:
        self.keys = record.keys
        self.seq = record.seq
        self.descending = descending

    def __lt__(self, other: SortKey) -> bool:
        if self.keys != other.keys:
            return self.keys > other.keys if self.descending else self.keys < other.keys
        return self.seq < other.seq


class ExternalSorter:
    """Sorts a record stream that need not fit in memory.

    Records accumulate until the buffer reaches the memory budget, at which
    point the sorted run is spilled as JSON lines; the runs are then merged
    lazily. Spill files live in a temporary directory removed on exit.
    """

    def __init__(self, *, descending: bool, memory_limit_mb: int, temp_dir: str | None) -> None:
        self._descending = descending
        self._buffer_limit = max(int(memory_limit_mb * MEGABYTE * _BUFFER_FRACTION), MEGABYTE)
        self._temp_dir = temp_dir
        self._workspace: TemporaryDirectory | None = None
        self._runs: list[str] = []

    def __enter__(self) -> ExternalSorter:
        self._workspace = TemporaryDirectory(prefix="csvmerge-", dir=self._temp_dir)
        return self

    def __exit__(self, *exc_info) -> None:
        self._workspace.cleanup()

    def sort(self, records: Iterable[Record]) -> Iterator[Record]:
        """Return the records in sorted order, spilling to disk as needed."""
        buffer: list[Record] = []
        buffered_bytes = 0
        for record in records:
            buffer.append(record)
            buffered_bytes += _estimated_size(record)
            if buffered_bytes >= self._buffer_limit:
                self._spill(buffer)
                buffer = []
                buffered_bytes = 0
        if not self._runs:
            return iter(self._sorted(buffer))
        if buffer:
            self._spill(buffer)
        return heapq.merge(*(_read_run(path) for path in self._runs), key=self._key)

    def _sorted(self, buffer: list[Record]) -> list[Record]:
        return sorted(buffer, key=self._key)

    def _key(self, record: Record) -> SortKey:
        return SortKey(record, self._descending)

    def _spill(self, buffer: list[Record]) -> None:
        path = os.path.join(self._workspace.name, f"run-{len(self._runs):05d}.jsonl")
        with open(path, "w", encoding="utf-8") as stream:
            for record in self._sorted(buffer):
                stream.write(json.dumps([record.keys, record.seq, record.row]) + "\n")
        self._runs.append(path)


def _read_run(path: str) -> Iterator[Record]:
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            yield Record(*json.loads(line))


def _estimated_size(record: Record) -> int:
    return sum(len(text) + _FIELD_OVERHEAD_BYTES for text in record.row) + _RECORD_OVERHEAD_BYTES
