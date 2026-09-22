"""Deciding where the sorted stream lands: one CSV, or a tree of part files.

With no partitioning flag the result is a single CSV, written to a file or to
stdout. With ``--partition-by``, ``--max-rows-per-file`` or
``--max-bytes-per-file`` it is a directory of ``part-00000.csv`` files - one
sequence per Hive-style partition directory, or one sequence directly under
the output directory when only the size limits apply.

The tree is built in a sibling staging directory and moved into place only
once it is complete, so a failed run leaves no partial output behind and an
earlier run's output stays readable until the moment it is replaced.
"""

from __future__ import annotations

import os
import shutil
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence, TextIO

from csvmerge.csvio import InputDialect, RowFormatter, write_csv
from csvmerge.errors import EXIT_USAGE, MergeError
from csvmerge.records import Record

_PART_NAME = "part-{:05d}.csv"


@dataclass(frozen=True)
class OutputLayout:
    """The partitioning flags, and what they say about the shape of the output."""

    partitioned: bool
    max_rows: int | None
    max_bytes: int | None

    @property
    def directory(self) -> bool:
        """Whether ``--output`` names a directory rather than a single CSV."""
        return self.partitioned or self.max_rows is not None or self.max_bytes is not None

    def full(self, rows: int, size: int, pending: int) -> bool:
        """Whether a part holding ``rows`` rows in ``size`` bytes has no room left.

        Both limits are honoured at once by cutting at whichever would be
        broken first. An empty part is never reported full, which is what puts
        a single row larger than ``--max-bytes-per-file`` in a file by itself.
        """
        return (self.max_rows is not None and rows >= self.max_rows) or (
            self.max_bytes is not None and size + pending > self.max_bytes
        )


def write_output(
    target: str,
    header: Sequence[str],
    records: Iterable[Record],
    dialect: InputDialect,
    layout: OutputLayout,
) -> None:
    """Write the ordered records out in whichever shape ``layout`` calls for."""
    if not layout.directory:
        write_csv(target, header, (record.cells for record in records), dialect)
        return
    _write_tree(Path(target), header, records, dialect, layout)


def _write_tree(
    target: Path,
    header: Sequence[str],
    records: Iterable[Record],
    dialect: InputDialect,
    layout: OutputLayout,
) -> None:
    if target.exists() and not target.is_dir():
        raise MergeError(f"{target}: --output must name a directory, but this is a file", EXIT_USAGE)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.partial-{os.getpid()}"
    staging.mkdir()
    formatter = RowFormatter(dialect)
    try:
        with closing(_PartFiles(staging, formatter.line(header), layout)) as parts:
            for record in records:
                parts.add(record.partition, formatter.line(record.cells))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _publish(staging, target)


def _publish(staging: Path, target: Path) -> None:
    """Move the finished tree onto ``target``, discarding an earlier run's output."""
    if not target.exists():
        staging.rename(target)
        return
    replaced = staging.with_name(f"{staging.name}.replaced")
    target.rename(replaced)
    staging.rename(target)
    shutil.rmtree(replaced)


class _PartFiles:
    """The ``part-xxxxx.csv`` sequence being written, cut on the layout's limits.

    Records arrive grouped by partition, so only one partition directory - and
    one file inside it - is ever open, however many partitions the merge
    produces. Part numbering restarts at zero in each partition directory.
    """

    def __init__(self, root: Path, header: str, layout: OutputLayout) -> None:
        self._root = root
        self._header = header
        self._header_bytes = len(header.encode("utf-8"))
        self._layout = layout
        self._partition: str | None = None
        self._directory = root
        self._handle: TextIO | None = None
        self._index = 0
        self._rows = 0
        self._bytes = 0

    def add(self, partition: str, line: str) -> None:
        """Append one rendered row, opening or cutting a part file as needed."""
        if partition != self._partition:
            self._open_partition(partition)
        size = len(line.encode("utf-8"))
        if self._handle is None or self._layout.full(self._rows, self._bytes, size):
            self._open_part()
        self._handle.write(line)
        self._rows += 1
        self._bytes += size

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def _open_partition(self, partition: str) -> None:
        self.close()
        self._partition = partition
        self._directory = self._root / partition if partition else self._root
        self._directory.mkdir(parents=True, exist_ok=True)
        self._index = 0

    def _open_part(self) -> None:
        self.close()
        path = self._directory / _PART_NAME.format(self._index)
        self._index += 1
        self._handle = path.open("w", encoding="utf-8", newline="")
        self._handle.write(self._header)
        self._rows, self._bytes = 0, self._header_bytes
