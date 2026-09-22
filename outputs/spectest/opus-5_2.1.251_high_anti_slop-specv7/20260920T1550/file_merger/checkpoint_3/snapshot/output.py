"""Where the sorted rows go: one CSV, or a directory of part files.

With no partitioning flag the rows become a single CSV, at a path or on
standard output.  Otherwise they become a directory of ``part-xxxxx.csv``
files: one tree of ``<column>=<value>`` directories per ``--partition-by``
combination, each cut into parts by ``--max-rows-per-file`` and
``--max-bytes-per-file``.

Rows leave the sort grouped by partition, so each partition directory is
written once, as its rows stream past, and is cut into parts whenever the next
row would push the current file past ``--max-rows-per-file`` or
``--max-bytes-per-file``.  Everything is built in a sibling directory that is
moved onto ``--output`` once the last row is written, so a failed run leaves
neither a partial tree nor a damaged previous one.
"""

from __future__ import annotations

import csv
import shutil
import tempfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from typing import Iterable, Iterator, Sequence, TextIO

from csv_io import CsvOptions, RowFormatter, open_output, output_dialect
from errors import UsageError

# One row on its way out: the partition it belongs to and its output cells.
OutputRow = tuple[list[str], list[str]]

_PART_NAME = "part-{:05d}.csv"


@dataclass(frozen=True)
class ShardLimits:
    """How large one part file may grow before the next one is started."""

    max_rows: int | None = None
    max_bytes: int | None = None

    @property
    def unlimited(self) -> bool:
        """True when neither limit was asked for, so files are never cut."""
        return self.max_rows is None and self.max_bytes is None

    def exceeded(self, rows: int, size: int) -> bool:
        """Would a file of ``rows`` data rows and ``size`` bytes be too large?"""
        too_many = self.max_rows is not None and rows > self.max_rows
        too_large = self.max_bytes is not None and size > self.max_bytes
        return too_many or too_large


@dataclass(frozen=True)
class OutputPlan:
    """Where the sorted rows go and how they are split up."""

    destination: str
    partition_columns: list[str]
    limits: ShardLimits

    def __post_init__(self) -> None:
        if self.partitioned and self.destination == "-":
            raise UsageError("--output must be a directory, not -, when the output is partitioned")

    @property
    def partitioned(self) -> bool:
        """True when the output is a directory rather than a single CSV."""
        return bool(self.partition_columns) or not self.limits.unlimited

    def write(self, header: Sequence[str], rows: Iterable[OutputRow], options: CsvOptions) -> None:
        """Write every sorted row to the destination this plan describes."""
        if self.partitioned:
            write_directory(
                Path(self.destination),
                header,
                rows,
                bool(self.partition_columns),
                self.limits,
                options,
            )
            return
        with open_output(self.destination) as stream:
            writer = csv.writer(stream, **output_dialect(options))
            writer.writerow(header)
            writer.writerows(cells for _partition, cells in rows)


def write_directory(
    destination: Path,
    header: Sequence[str],
    rows: Iterable[OutputRow],
    partitioned: bool,
    limits: ShardLimits,
    options: CsvOptions,
) -> None:
    """Write ``rows`` under ``destination``, replacing it in one step.

    Without field partitioning every row belongs to the same group and the
    parts are written directly under ``destination``; with it, ``rows`` is cut
    into one group per partition, each landing in its own directory tree.
    """
    with _staging(destination) as staging:
        groups = groupby(rows, key=itemgetter(0)) if partitioned else [((), rows)]
        for segments, group in groups:
            directory = staging.joinpath(*segments)
            directory.mkdir(parents=True, exist_ok=True)
            with closing(_PartFiles(directory, header, limits, options)) as files:
                for _segments, cells in group:
                    files.write(cells)


class _PartFiles:
    """The ``part-xxxxx.csv`` sequence of one directory.

    The first file is opened with the header straight away, so a directory
    always holds at least one valid CSV.  A row that does not fit the current
    file starts the next one; a row too large to fit an empty file is written
    to a file of its own and is allowed to exceed the byte limit.
    """

    def __init__(
        self,
        directory: Path,
        header: Sequence[str],
        limits: ShardLimits,
        options: CsvOptions,
    ) -> None:
        self._directory = directory
        self._limits = limits
        self._formatter = RowFormatter(options)
        self._header = self._formatter.render(header)
        self._files = 0
        self._rows = 0
        self._size = 0
        self._handle: TextIO = self._start()

    def write(self, cells: Sequence[str]) -> None:
        """Append one row, cutting a new file first if it would not fit."""
        text = self._formatter.render(cells)
        size = len(text.encode("utf-8"))
        if self._rows and self._limits.exceeded(self._rows + 1, self._size + size):
            self._handle.close()
            self._handle = self._start()
        self._handle.write(text)
        self._rows += 1
        self._size += size

    def close(self) -> None:
        self._handle.close()

    def _start(self) -> TextIO:
        """Open the next part file and write the header into it."""
        path = self._directory / _PART_NAME.format(self._files)
        self._files += 1
        handle = path.open("w", encoding="utf-8", newline="")
        handle.write(self._header)
        self._rows = 0
        self._size = len(self._header.encode("utf-8"))
        return handle


@contextmanager
def _staging(destination: Path) -> Iterator[Path]:
    """Yield a sibling directory that is moved onto ``destination`` on success."""
    if destination.exists() and not destination.is_dir():
        raise UsageError(f"{destination}: --output must be a directory when partitioning")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(dir=destination.parent, prefix=f".{destination.name}.", suffix=".part")
    )
    try:
        yield staging
        _move_into_place(staging, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _move_into_place(staging: Path, destination: Path) -> None:
    """Rename ``staging`` to ``destination``, discarding an earlier output."""
    if not destination.exists():
        staging.rename(destination)
        return
    previous = staging.with_suffix(".old")
    destination.rename(previous)
    staging.rename(destination)
    shutil.rmtree(previous)
