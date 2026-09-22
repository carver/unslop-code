"""Reading input CSVs: dialect handling and header-aligned records."""

from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass

from .errors import MergeError


@dataclass(frozen=True)
class InputDialect:
    """Input CSV dialect; only quoting is configurable (see AMBIGUITIES T7)."""

    quotechar: str = '"'
    escapechar: str | None = None

    def reader(self, stream):
        return csv.reader(
            stream,
            delimiter=",",
            quotechar=self.quotechar,
            doublequote=self.escapechar is None,
            escapechar=self.escapechar,
        )


@contextmanager
def _open_csv(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as stream:
            yield stream
    except OSError as error:
        raise MergeError(f"cannot read input {path}: {error}") from error


def read_header(path, dialect):
    """Return the column names of `path`, or an empty list for an empty file."""
    with _open_csv(path) as stream:
        return next(dialect.reader(stream), [])


def read_records(path, dialect):
    """Yield ``(line_number, {column: text or None})`` for each data row.

    Blank cells and columns absent from the row become ``None``; duplicate header
    names keep their first occurrence (AMBIGUITIES T16).
    """
    with _open_csv(path) as stream:
        rows = dialect.reader(stream)
        header = next(rows, None)
        if header is None:
            return
        for line_number, row in enumerate(rows, start=2):
            yield line_number, _align(header, row)


def _align(header, row):
    record = {}
    for name, text in zip(header, row):
        record.setdefault(name, text or None)
    for name in header[len(row):]:
        record.setdefault(name, None)
    return record
