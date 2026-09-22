"""Writing the sorted stream out as a tree of part files, atomically."""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Sequence

from .csvio import render_row
from .errors import EXIT_USAGE, MergeError

#: Part files are numbered from zero within their own directory.
_PART_NAME = "part-{:05d}.csv"

#: Prefix shared by the staging directory and the displaced previous output, so
#: both are recognisable as this tool's leftovers if a run is killed outright.
_TEMP_PREFIX = ".merge-files-"


@dataclass(frozen=True)
class ShardLimits:
    """The cutting rules: at most so many rows, and at most so many bytes."""

    max_rows: int | None
    max_bytes: int | None

    def cut_before(self, rows: int, used_bytes: int, row_bytes: int) -> bool:
        """Whether the next row starts a new file instead of joining the current one.

        The byte rule never cuts an empty file, so a row larger than the whole
        budget lands in a file of its own rather than in no file at all.
        """
        if self.max_rows is not None and rows >= self.max_rows:
            return True
        return (self.max_bytes is not None and rows > 0
                and used_bytes + row_bytes > self.max_bytes)


class ShardedWriter:
    """Writes rows into `part-xxxxx.csv` files, one numbered sequence per directory.

    Rows arrive grouped by directory (the sort key leads with the partition
    path), so only the current part file is ever open.
    """

    def __init__(self, root: str, header: Sequence[str], limits: ShardLimits):
        self._root = root
        self._header = render_row(header)
        self._limits = limits
        self._directory: str | None = None
        self._handle = None
        self._part = 0
        self._rows = 0
        self._bytes = 0

    def __enter__(self) -> "ShardedWriter":
        return self

    def __exit__(self, *exception) -> None:
        self._close_part()

    def begin(self, directory: str) -> None:
        """Open a directory's part sequence, giving it a header even with no rows."""
        os.makedirs(os.path.join(self._root, directory), exist_ok=True)
        self._directory = directory
        self._part = 0
        self._open_part()

    def write(self, directory: str, row: Sequence[str]) -> None:
        """Append one row, moving to a new directory or new part file as needed."""
        line = render_row(row)
        size = len(line.encode("utf-8"))
        if directory != self._directory:
            self.begin(directory)
        elif self._limits.cut_before(self._rows, self._bytes, size):
            self._part += 1
            self._open_part()
        self._handle.write(line)
        self._rows += 1
        self._bytes += size

    def _open_part(self) -> None:
        self._close_part()
        path = os.path.join(self._root, self._directory, _PART_NAME.format(self._part))
        self._handle = open(path, "w", encoding="utf-8", newline="")
        self._handle.write(self._header)
        self._rows = 0
        self._bytes = len(self._header.encode("utf-8"))

    def _close_part(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


@contextmanager
def staged_directory(path: str):
    """Build the output tree in a sibling temp directory and move it in on success.

    The destination therefore only ever appears finished: a run that fails takes
    its partial files with it, and a run that succeeds replaces whatever the
    destination held before with exactly the tree it produced.
    """
    target = os.path.abspath(path)
    if os.path.exists(target) and not os.path.isdir(target):
        raise MergeError(f"{path}: --output must be a directory when partitioning",
                         EXIT_USAGE)
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(dir=parent, prefix=_TEMP_PREFIX)
    try:
        yield staging
    except BaseException:
        shutil.rmtree(staging)
        raise
    _move_into_place(staging, target)


def _move_into_place(staging: str, target: str) -> None:
    """Rename `staging` onto `target`, discarding anything the destination held."""
    if os.path.exists(target):
        displaced = tempfile.mkdtemp(dir=os.path.dirname(target), prefix=_TEMP_PREFIX)
        os.rename(target, displaced)
        os.rename(staging, target)
        shutil.rmtree(displaced)
        return
    os.rename(staging, target)
