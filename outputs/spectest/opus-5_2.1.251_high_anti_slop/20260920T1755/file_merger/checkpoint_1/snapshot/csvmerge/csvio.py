"""CSV input and output: dialect handling, header alignment, result writing."""

from __future__ import annotations

import csv
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

STDOUT_TARGET = "-"


@dataclass(frozen=True)
class InputDialect:
    """How input cells are quoted, escaped and spelled when null.

    Inputs are comma separated UTF-8 with a header row; only the quoting
    details and the null spelling are configurable.
    """

    quotechar: str = '"'
    escapechar: str | None = None
    null_literal: str = ""

    def reader_args(self) -> dict:
        return {
            "delimiter": ",",
            "quotechar": self.quotechar,
            "escapechar": self.escapechar,
            "doublequote": self.escapechar is None,
        }

    def is_null(self, text: str | None) -> bool:
        return text is None or text == "" or text == self.null_literal


@contextmanager
def open_csv(path: str, dialect: InputDialect) -> Iterator[tuple[list[str], Iterator[list[str]]]]:
    """Open an input file and yield its header together with its remaining rows."""
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, **dialect.reader_args())
        yield next(reader, []), reader


def iter_aligned_rows(
    path: str, column_names: Sequence[str], dialect: InputDialect
) -> Iterator[tuple[int, tuple[str | None, ...]]]:
    """Yield ``(line_number, cells)`` with one cell per requested column.

    Columns the file does not carry - and cells missing from a short row -
    come back as ``None``. Columns the file carries but the schema does not
    are dropped.
    """
    with open_csv(path, dialect) as (header, rows):
        positions = [header.index(name) if name in header else None for name in column_names]
        for line_number, row in enumerate(rows, start=2):
            yield line_number, tuple(
                row[position] if position is not None and position < len(row) else None
                for position in positions
            )


@contextmanager
def _open_output(path: str):
    if path == STDOUT_TARGET:
        yield sys.stdout
    else:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            yield handle


def write_csv(path: str, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    """Write the header and rows to a file, or to stdout for ``-``."""
    with _open_output(path) as stream:
        writer = csv.writer(stream, delimiter=",", quotechar='"', doublequote=True, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
