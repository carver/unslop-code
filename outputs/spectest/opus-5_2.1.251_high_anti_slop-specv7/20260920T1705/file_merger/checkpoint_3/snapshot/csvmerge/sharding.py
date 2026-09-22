"""Writing a sorted stream into a directory of ``part-xxxxx.csv`` files.

The stream arrives grouped by partition — the sort puts every partition's rows
together — so one directory is filled at a time and only one file is ever open.
Each part file repeats the header and is cut whenever another row would break
``--max-rows-per-file`` or ``--max-bytes-per-file``.  The whole tree is built
in a sibling temporary directory and moved onto the destination once the last
row is out, so a failed run leaves nothing behind.
"""

from __future__ import annotations

import itertools
import os
import shutil
import tempfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable, Iterator, Sequence

from .csvio import RowRenderer
from .sorting import Record

_PART_NAME = "part-{index:05d}.csv"


@dataclass(frozen=True)
class ShardLimits:
    """How large one part file may grow; ``None`` means unbounded."""

    max_rows: int | None = None
    max_bytes: int | None = None


class PartWriter:
    """The sequence of part files inside one partition directory."""

    def __init__(self, directory: Path, header: str, limits: ShardLimits) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory
        self._header = header
        self._header_bytes = len(header.encode("utf-8"))
        self._limits = limits
        self._handle: IO[str] | None = None
        self._parts = 0
        self._rows = 0
        self._bytes = 0

    def write(self, line: str) -> None:
        """Append one rendered row, starting a new part file when needed."""
        size = len(line.encode("utf-8"))
        if self._handle is None or self._is_full(size):
            self._start_part()
        self._handle.write(line)
        self._rows += 1
        self._bytes += size

    def close(self) -> None:
        """Close the part file currently open, if any."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def _is_full(self, size: int) -> bool:
        """Would appending a row of ``size`` bytes break either limit?

        A row larger than the byte limit still has to go somewhere, so it is
        given a file of its own rather than cutting an empty one before it.
        """
        rows_full = self._limits.max_rows is not None and self._rows >= self._limits.max_rows
        bytes_full = (
            self._limits.max_bytes is not None
            and self._rows > 0
            and self._bytes + size > self._limits.max_bytes
        )
        return rows_full or bytes_full

    def _start_part(self) -> None:
        self.close()
        path = self._directory / _PART_NAME.format(index=self._parts)
        self._handle = path.open("w", newline="", encoding="utf-8")
        self._handle.write(self._header)
        self._parts += 1
        self._rows = 0
        self._bytes = self._header_bytes


def write_shards(
    destination: str,
    header: Sequence[str],
    records: Iterable[Record],
    null_literal: str,
    limits: ShardLimits,
) -> None:
    """Write ``records`` under ``destination``, one directory per partition."""
    renderer = RowRenderer(null_literal)
    header_line = renderer.render(header)
    with atomic_directory(destination) as root:
        for partition, group in itertools.groupby(records, key=lambda record: record.partition):
            with closing(PartWriter(root.joinpath(*partition), header_line, limits)) as writer:
                for record in group:
                    writer.write(renderer.render(record.cells))


@contextmanager
def atomic_directory(destination: str) -> Iterator[Path]:
    """Yield a temporary directory that is moved onto ``destination`` on success.

    Nothing is visible at the destination until every part file has been
    written; a directory already there is replaced, and a run that raises takes
    its temporary tree with it.
    """
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".{target.name}.partial-"))
    try:
        yield scratch
        if target.is_dir():
            shutil.rmtree(target)
        os.replace(scratch, target)
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
