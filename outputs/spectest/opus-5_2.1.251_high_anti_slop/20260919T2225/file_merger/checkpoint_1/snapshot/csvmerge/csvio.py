"""Low-level CSV input and output plumbing."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import IO

from .dialect import CsvDialect


@contextmanager
def open_csv(path: str, dialect: CsvDialect) -> Iterator[tuple[list[str], Iterator[list[str]]]]:
    """Open ``path`` and yield its header row together with its data rows."""
    with open(path, newline="", encoding="utf-8") as stream:
        reader = dialect.reader(stream)
        header = next(reader, [])
        yield header, (row for row in reader if row)


def read_header(path: str, dialect: CsvDialect) -> list[str]:
    """Return the column names of ``path`` without reading its data rows."""
    with open_csv(path, dialect) as (header, _rows):
        return header


@contextmanager
def open_output(path: str) -> Iterator[IO[str]]:
    """Open the output sink: ``-`` means stdout, anything else a UTF-8 file."""
    if path == "-":
        yield sys.stdout
    else:
        with open(path, "w", newline="", encoding="utf-8") as stream:
            yield stream


def write_csv(stream: IO[str], dialect: CsvDialect, header: Iterable[str], rows: Iterable[list[str]]) -> None:
    """Write the header followed by ``rows``, streaming them one at a time."""
    writer = dialect.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)
