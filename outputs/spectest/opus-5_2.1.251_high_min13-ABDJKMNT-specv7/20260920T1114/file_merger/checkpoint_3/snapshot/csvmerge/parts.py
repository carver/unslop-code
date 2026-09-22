"""Cutting a sorted row stream into `part-xxxxx.csv` files under a directory.

Rows arrive grouped by partition — the sort key starts with the partition
segments — so one part file is open at a time. Within a partition, a new part
starts as soon as adding a row would break a row or byte limit; a row that
cannot fit in an empty file is written anyway, alone, as the spec allows.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO

from csvmerge.dialect import CsvDialect
from csvmerge.errors import EXIT_ERROR, MergeError

PART_NAME = "part-{index:05d}.csv"


@dataclass(frozen=True)
class Limits:
    """How much one part file may hold; ``None`` means unlimited."""

    max_rows: int | None = None
    max_bytes: int | None = None

    def exceeded(self, rows: int, size: int) -> bool:
        """True when a part of `rows` rows and `size` bytes breaks a limit."""
        return (self.max_rows is not None and rows > self.max_rows) or (
            self.max_bytes is not None and size > self.max_bytes
        )


def write_parts(
    root: Path,
    dialect: CsvDialect,
    header: list[str],
    limits: Limits,
    rows: Iterable[tuple[tuple[str, ...], list[str]]],
) -> None:
    """Write `(segments, cells)` pairs as part files under `root`."""
    with closing(_PartitionedOutput(root, dialect.format_row(header), limits)) as output:
        try:
            for segments, cells in rows:
                output.write(segments, dialect.format_row(cells))
        except OSError as error:
            raise MergeError(
                f"cannot write output {root}: {error}", EXIT_ERROR
            ) from error


class _PartitionedOutput:
    """Routes rows into the part files of the partition they belong to."""

    def __init__(self, root: Path, header: str, limits: Limits):
        self._root = root
        self._header = header
        self._limits = limits
        self._segments: tuple[str, ...] | None = None
        self._parts: _PartFiles | None = None

    def write(self, segments: tuple[str, ...], line: str) -> None:
        """Append one rendered row to the current partition, opening it if new."""
        if segments != self._segments:
            self.close()
            directory = self._root.joinpath(*segments)
            directory.mkdir(parents=True, exist_ok=True)
            self._parts = _PartFiles(directory, self._header, self._limits)
            self._segments = segments
        self._parts.write(line)

    def close(self) -> None:
        """Finish the partition being written, if any."""
        if self._parts is not None:
            self._parts.close()
            self._parts = None


class _PartFiles:
    """The numbered part files of one partition directory."""

    def __init__(self, directory: Path, header: str, limits: Limits):
        self._directory = directory
        self._header = header
        self._limits = limits
        self._index = 0
        self._handle: TextIO | None = None
        self._rows = 0
        self._bytes = 0

    def write(self, line: str) -> None:
        """Append one rendered row, starting a new part where a limit says so."""
        size = len(line.encode("utf-8"))
        if self._handle is None or (
            self._rows and self._limits.exceeded(self._rows + 1, self._bytes + size)
        ):
            self._start_part()
        self._handle.write(line)
        self._rows += 1
        self._bytes += size

    def close(self) -> None:
        """Close the part file currently being written, if any."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def _start_part(self) -> None:
        self.close()
        path = self._directory / PART_NAME.format(index=self._index)
        self._handle = open(path, "w", encoding="utf-8", newline="")
        self._handle.write(self._header)
        self._index += 1
        self._rows = 0
        self._bytes = len(self._header.encode("utf-8"))
