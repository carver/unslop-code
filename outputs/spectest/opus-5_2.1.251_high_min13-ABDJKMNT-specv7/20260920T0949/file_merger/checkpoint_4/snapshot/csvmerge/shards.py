"""Cutting one stream of rows into the ``part-NNNNN.csv`` files of a directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShardLimits:
    """How large one part file may grow; ``None`` means no limit of that kind."""

    max_rows: int | None = None
    max_bytes: int | None = None

    @property
    def bounded(self) -> bool:
        """Whether either file limit was given."""
        return self.max_rows is not None or self.max_bytes is not None

    def must_cut(self, rows: int, size: int, addition: int) -> bool:
        """Whether a file holding ``rows`` rows in ``size`` bytes must be closed
        before a row of ``addition`` bytes is appended.

        An empty file always takes the next row, which is what lets a row longer
        than ``max_bytes`` sit in a file of its own.
        """
        if rows == 0:
            return False
        if self.max_rows is not None and rows >= self.max_rows:
            return True
        return self.max_bytes is not None and size + addition > self.max_bytes


class ShardWriter:
    """The ``part-00000.csv``, ``part-00001.csv``, ... sequence of one directory.

    Every file repeats the header, and the header counts towards the byte limit
    of the file it opens.
    """

    def __init__(self, directory: Path, header: str, limits: ShardLimits):
        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory
        self._header = header
        self._limits = limits
        self._index = -1
        self._handle = None
        self._start_file()

    def write(self, text: str) -> None:
        size = len(text.encode("utf-8"))
        if self._limits.must_cut(self._rows, self._size, size):
            self._start_file()
        self._handle.write(text)
        self._rows += 1
        self._size += size

    def close(self) -> None:
        self._handle.close()

    def _start_file(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._index += 1
        path = self._directory / f"part-{self._index:05d}.csv"
        self._handle = open(path, "w", encoding="utf-8", newline="")
        self._handle.write(self._header)
        self._rows = 0
        self._size = len(self._header.encode("utf-8"))
