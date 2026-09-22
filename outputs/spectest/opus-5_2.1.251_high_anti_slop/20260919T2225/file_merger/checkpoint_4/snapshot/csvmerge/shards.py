"""Writing a sorted record stream into a directory tree of ``part-xxxxx.csv`` files."""

from __future__ import annotations

import itertools
import os
import shutil
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from tempfile import mkdtemp
from typing import IO

from .dialect import CsvDialect, RowFormatter
from .sorting import Record

#: Part files are numbered from zero within each partition directory.
PART_NAME = "part-{:05d}.csv"


@dataclass(frozen=True)
class ShardLimits:
    """How large one part file may grow. ``None`` on both means one file per partition."""

    max_rows: int | None = None
    max_bytes: int | None = None

    @property
    def bounded(self) -> bool:
        return self.max_rows is not None or self.max_bytes is not None

    def exceeded(self, rows: int, size: int) -> bool:
        """Report whether a part holding ``rows`` data rows in ``size`` bytes is too large."""
        return (self.max_rows is not None and rows > self.max_rows) or (
            self.max_bytes is not None and size > self.max_bytes
        )


class ShardWriter:
    """Fills one directory with sequentially numbered part files.

    The current part is closed and the next one started as soon as a row would
    break either limit. A row too large for even an empty part is written
    anyway, so it ends up in a file of its own.
    """

    def __init__(self, directory: str, header: str, limits: ShardLimits) -> None:
        self._directory = directory
        self._header = header
        self._limits = limits
        self._stream: IO[str] | None = None
        self._parts = 0
        self._rows = 0
        self._size = 0

    def write(self, text: str) -> None:
        size = len(text.encode("utf-8"))
        if self._stream is not None and self._limits.exceeded(self._rows + 1, self._size + size):
            self.close()
        if self._stream is None:
            self._start_part()
        self._stream.write(text)
        self._rows += 1
        self._size += size

    def close(self) -> None:
        """Close the open part, if any. A partition with no rows writes no file."""
        if self._stream is None:
            return
        self._stream.close()
        self._stream = None

    def _start_part(self) -> None:
        path = os.path.join(self._directory, PART_NAME.format(self._parts))
        self._stream = open(path, "w", newline="", encoding="utf-8")
        self._stream.write(self._header)
        self._parts += 1
        self._rows = 0
        self._size = len(self._header.encode("utf-8"))


def write_tree(
    root: str,
    dialect: CsvDialect,
    header: Sequence[str],
    limits: ShardLimits,
    records: Iterable[Record],
) -> None:
    """Write sorted records under ``root``, one shard writer per partition directory.

    The sort orders records on their partition segments before their sort key,
    so every partition arrives as one contiguous run and only a single file is
    ever open, however many partitions the data has.
    """
    render = RowFormatter(dialect)
    header_text = render(header)
    for segments, group in itertools.groupby(records, key=lambda record: record.partition):
        shard = ShardWriter(_partition_directory(root, segments), header_text, limits)
        for record in group:
            shard.write(render(record.row))
        shard.close()


@contextmanager
def atomic_directory(path: str) -> Iterator[str]:
    """Build the output tree in a sibling directory and move it into place on success.

    A failed run leaves nothing behind but whatever was already at ``path``; a
    successful one replaces that directory wholesale, so a rerun never mixes
    fresh part files with stale ones.
    """
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    pending = mkdtemp(prefix=".csvmerge-", dir=parent)
    os.chmod(pending, _default_directory_mode())
    try:
        yield pending
    except BaseException:
        shutil.rmtree(pending)
        raise
    _move_into_place(pending, path)


def _move_into_place(pending: str, path: str) -> None:
    if not os.path.exists(path):
        os.rename(pending, path)
        return
    displaced = pending + "-displaced"
    os.rename(path, displaced)
    os.rename(pending, path)
    shutil.rmtree(displaced)


def _default_directory_mode() -> int:
    """Return the mode a plain ``mkdir`` would use; ``mkdtemp`` creates a private 0700 one."""
    mask = os.umask(0)
    os.umask(mask)
    return 0o777 & ~mask


def _partition_directory(root: str, segments: Sequence[str]) -> str:
    directory = os.path.join(root, *segments)
    os.makedirs(directory, exist_ok=True)
    return directory
