"""Global ordering: key encoding, direction-aware comparison, external merge sort."""

from __future__ import annotations

import heapq
import json
import tempfile
from datetime import date, datetime

from .coltypes import KeptText, render

#: Ordering classes for a single key cell. Nulls always sort as the lowest class,
#: values that failed to cast (``keep-string``) as the highest (AMBIGUITIES T8).
_NULL, _TYPED, _TEXT = 0, 1, 2

#: Rough per-row and per-cell cost of holding a buffered row in memory, used to
#: decide when to spill. Estimates, not measurements: Python objects carry far more
#: overhead than their text length.
_ROW_OVERHEAD_BYTES = 200
_CELL_OVERHEAD_BYTES = 60


def encode_value(value):
    """Encode one key cell as a JSON-friendly ``[class, comparable]`` pair."""
    if value is None:
        return [_NULL]
    if isinstance(value, KeptText):
        return [_TEXT, value.text]
    if isinstance(value, bool):
        return [_TYPED, int(value)]
    if isinstance(value, (datetime, date)):
        return [_TYPED, render(value, "")]
    return [_TYPED, value]


def _cell_lt(mine, theirs, descending):
    """Compare two encoded key cells known to differ."""
    if mine[0] == _NULL or theirs[0] == _NULL:
        return theirs[0] == _NULL if descending else mine[0] == _NULL
    if mine[0] != theirs[0]:
        return mine[0] > theirs[0] if descending else mine[0] < theirs[0]
    return mine[1] > theirs[1] if descending else mine[1] < theirs[1]


class SortOrder:
    """Builds and compares sort keys for the configured `--key` field paths."""

    def __init__(self, paths, descending):
        self._paths = tuple(paths)
        self._descending = descending

    def key_of(self, values):
        """Encode the key vector of a row given its values in schema order."""
        return [encode_value(path.extract(values)) for path in self._paths]

    def ranked(self, record):
        return _Ranked(record, self._descending)


class _Ranked:
    """Sort-key wrapper: compares by key vector, then by input appearance."""

    __slots__ = ("_key", "_index", "_descending")

    def __init__(self, record, descending):
        self._key, self._index = record[0], record[1]
        self._descending = descending

    def __lt__(self, other):
        for mine, theirs in zip(self._key, other._key):
            if mine != theirs:
                return _cell_lt(mine, theirs, self._descending)
        return self._index < other._index


class ExternalSorter:
    """Sorts more rows than fit in memory by spilling sorted runs to temp files.

    Rows are buffered until their estimated footprint exceeds ``budget_bytes``; the
    buffer is then sorted and written to a temporary file as JSON lines. ``merged``
    performs a k-way merge over the spilled runs and the remaining buffer, so the
    peak footprint stays at one buffer plus one row per run.
    """

    def __init__(self, order, budget_bytes, temp_dir=None):
        self._order = order
        self._budget_bytes = max(budget_bytes, 1)
        self._temp_dir = temp_dir
        self._buffer = []
        self._buffered_bytes = 0
        self._runs = []

    def add(self, key, index, cells, partition=None):
        """Buffer one row: its sort key, its input position, its cells, its partition."""
        self._buffer.append([key, index, cells, partition])
        self._buffered_bytes += _ROW_OVERHEAD_BYTES + sum(
            len(cell) + _CELL_OVERHEAD_BYTES for cell in cells
        )
        if self._buffered_bytes > self._budget_bytes:
            self._spill()

    def merged(self):
        """Yield ``(cells, partition)`` for every row in sort order."""
        runs = [self._read_run(handle) for handle in self._runs]
        runs.append(iter(self._sorted_buffer()))
        for record in heapq.merge(*runs, key=self._order.ranked):
            yield record[2], record[3]

    def close(self):
        """Release the temporary files holding spilled runs."""
        while self._runs:
            self._runs.pop().close()

    def _sorted_buffer(self):
        self._buffer.sort(key=self._order.ranked)
        return self._buffer

    def _spill(self):
        handle = tempfile.TemporaryFile(mode="w+", encoding="utf-8", dir=self._temp_dir)
        handle.writelines(json.dumps(record) + "\n" for record in self._sorted_buffer())
        self._runs.append(handle)
        self._buffer = []
        self._buffered_bytes = 0

    @staticmethod
    def _read_run(handle):
        handle.seek(0)
        return (json.loads(line) for line in handle)
