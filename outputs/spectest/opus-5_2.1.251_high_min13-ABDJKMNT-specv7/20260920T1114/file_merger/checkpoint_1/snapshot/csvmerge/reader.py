"""Reading input CSVs under the configurable input dialect."""

from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from csvmerge.errors import MergeError


@dataclass(frozen=True)
class InputDialect:
    """How input cells are quoted, escaped and spelled when null.

    The output dialect is fixed by the spec, so these settings apply to reading only.
    """

    quotechar: str = '"'
    escapechar: str = "\\"
    null_literal: str = ""

    def is_null(self, text: str) -> bool:
        """Empty cells are missing values, as is the configured null literal."""
        return text == "" or text == self.null_literal


@contextmanager
def open_table(path: str, dialect: InputDialect) -> Iterator[tuple[list[str], Iterator]]:
    """Open `path` and yield its header row together with an iterator of data rows."""
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as error:
        raise MergeError(f"cannot read input {path}: {error}") from error
    with handle:
        rows = csv.reader(
            handle,
            delimiter=",",
            quotechar=dialect.quotechar,
            escapechar=dialect.escapechar,
            doublequote=True,
        )
        yield next(rows, []), rows


def iter_aligned_rows(
    path: str, dialect: InputDialect, column_names: list[str]
) -> Iterator[list[str]]:
    """Yield each data row as raw cells in `column_names` order.

    Columns the file does not have, and cells a short row does not reach, read as
    empty text; columns the caller did not ask for are dropped. Blank lines carry no
    cells at all and are skipped rather than turned into all-null rows.
    """
    with open_table(path, dialect) as (header, rows):
        positions = [
            header.index(name) if name in header else None for name in column_names
        ]
        for row in filter(None, rows):
            yield [
                row[position] if position is not None and position < len(row) else ""
                for position in positions
            ]
