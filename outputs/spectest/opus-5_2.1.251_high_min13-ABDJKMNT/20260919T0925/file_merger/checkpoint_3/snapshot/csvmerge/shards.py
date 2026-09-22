"""Cutting the sorted stream into `part-xxxxx.csv` files under an output directory.

One `ShardWriter` owns the numbered files of a single directory; `ShardTree` routes
rows to the writer for their partition. Rows arrive grouped by partition — the
partition directory leads the sort key — so only one writer is open at a time.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from .errors import MergeError


@dataclass(frozen=True)
class ShardLimits:
    """The `--max-rows-per-file` / `--max-bytes-per-file` pair; `None` means unset."""

    max_rows: int | None = None
    max_bytes: int | None = None

    def __post_init__(self):
        _require_positive("--max-rows-per-file", self.max_rows)
        _require_positive("--max-bytes-per-file", self.max_bytes)

    @property
    def unset(self):
        return self.max_rows is None and self.max_bytes is None

    def cuts_before(self, rows, size, addition):
        """Would appending a row of `addition` bytes breach either limit?

        A file that holds no data row yet is never cut, which is how a row larger
        than `--max-bytes-per-file` ends up in a file by itself.
        """
        if rows == 0:
            return False
        if self.max_rows is not None and rows >= self.max_rows:
            return True
        return self.max_bytes is not None and size + addition > self.max_bytes


def _require_positive(flag, value):
    if value is not None and value < 1:
        raise MergeError(f"{flag} must be a positive integer, not {value}")


def line_formatter(dialect):
    """Return a function rendering one row as the exact text written to a part file."""
    buffer = io.StringIO()
    writer = dialect.writer(buffer)

    def format_row(cells):
        buffer.seek(0)
        buffer.truncate()
        writer.writerow(cells)
        return buffer.getvalue()

    return format_row


class ShardWriter:
    """The `part-00000.csv`, `part-00001.csv`, … sequence of one directory.

    Every file opens with the header row, and the file in progress is cut as soon as
    the next row would breach a limit; with no limits the sequence is one file.
    """

    def __init__(self, directory, header, dialect, limits):
        self._directory = directory
        self._limits = limits
        self._format = line_formatter(dialect)
        self._header = self._format(header)
        self._handle = None
        self._next_part = 0
        self._start_file()

    def write(self, cells):
        line = self._format(cells)
        size = len(line.encode("utf-8"))
        if self._limits.cuts_before(self._rows, self._bytes, size):
            self._start_file()
        self._handle.write(line)
        self._rows += 1
        self._bytes += size

    def close(self):
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def _start_file(self):
        """Close the file in progress and open the next one on its header row."""
        self.close()
        path = self._directory / f"part-{self._next_part:05d}.csv"
        self._next_part += 1
        self._handle = open(path, "w", encoding="utf-8", newline="")
        self._handle.write(self._header)
        self._rows = 0
        self._bytes = len(self._header.encode("utf-8"))


class ShardTree:
    """Routes rows into one shard sequence per partition directory under `root`.

    A directory is created, and its numbering starts, the first time a row lands in
    it; the sorted stream never returns to a directory it has left.
    """

    def __init__(self, root, header, dialect, limits):
        self._root = root
        self._header = header
        self._dialect = dialect
        self._limits = limits
        self._current = None
        self._writer = None

    def start(self, partition):
        """Begin the shard sequence of `partition`, `None` meaning `root` itself."""
        if self._writer is not None and partition == self._current:
            return
        self.close()
        self._current = partition
        self._writer = ShardWriter(self._make(partition), self._header, self._dialect, self._limits)

    def write(self, cells, partition):
        self.start(partition)
        self._writer.write(cells)

    def close(self):
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def _make(self, partition):
        directory = self._root if partition is None else self._root.joinpath(*partition.split("/"))
        directory.mkdir(parents=True, exist_ok=True)
        return directory


def write_shards(root, header, rows, dialect, limits, field_partitioned):
    """Write `(cells, partition)` pairs as part files under `root`.

    Without field partitioning the whole stream is one sequence directly under
    `root`, and an empty stream still leaves a header-only `part-00000.csv`
    (AMBIGUITIES T37); with field partitioning a directory exists only once a row
    has landed in it.
    """
    tree = ShardTree(root, header, dialect, limits)
    try:
        if not field_partitioned:
            tree.start(None)
        for cells, partition in rows:
            tree.write(cells, partition)
    finally:
        tree.close()
