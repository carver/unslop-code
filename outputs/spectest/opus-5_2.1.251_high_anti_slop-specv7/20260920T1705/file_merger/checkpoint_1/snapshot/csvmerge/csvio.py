"""CSV reading and writing with the tool's fixed dialects.

Inputs are UTF-8, comma delimited and carry a header row.  Their quoting can be
tuned from the command line; the output dialect is fixed by the spec: comma
delimited, ``"`` quoted, quotes escaped by doubling and ``\\n`` line endings.
"""

from __future__ import annotations

import csv
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import IO, Iterator, Sequence

_OUTPUT_DIALECT = {
    "delimiter": ",",
    "quotechar": '"',
    "doublequote": True,
    "escapechar": None,
    "lineterminator": "\n",
    "quoting": csv.QUOTE_MINIMAL,
}


@dataclass(frozen=True)
class InputDialect:
    """How input cells are quoted, escaped and spelled when null."""

    quotechar: str = '"'
    escapechar: str | None = "\\"
    null_literal: str = ""

    @property
    def null_texts(self) -> frozenset[str]:
        """Cell texts read as null: the empty cell and the null literal."""
        return frozenset({"", self.null_literal})

    def reader_options(self) -> dict[str, object]:
        """Keyword arguments for :func:`csv.reader`."""
        return {
            "delimiter": ",",
            "quotechar": self.quotechar,
            "doublequote": True,
            "escapechar": self.escapechar,
        }


def read_header(path: str, dialect: InputDialect) -> list[str]:
    """Return the column names of a file, or an empty list if it has none."""
    with open(path, newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle, **dialect.reader_options()), [])


def read_rows(path: str, dialect: InputDialect) -> Iterator[dict[str, str | None]]:
    """Yield each data row as a mapping of column name to text.

    Empty cells and cells holding the null literal map to ``None``; columns
    absent from the file's header are simply missing from the mapping, which
    lets schema inference tell "not provided here" apart from "empty here".
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle, **dialect.reader_options())
        header = next(reader, None)
        if header is None:
            return
        nulls = dialect.null_texts
        for row in reader:
            yield {
                name: None if text in nulls else text
                for name, text in zip(header, row)
            }


@contextmanager
def open_output(destination: str) -> Iterator[IO[str]]:
    """Open the output destination, or hand out stdout for ``-``."""
    if destination == "-":
        yield sys.stdout
        return
    with open(destination, "w", newline="", encoding="utf-8") as handle:
        yield handle


def write_rows(
    handle: IO[str],
    header: Sequence[str],
    rows: Iterator[Sequence[str | None]],
    null_literal: str,
) -> None:
    """Write the header and every row, spelling ``None`` as the null literal."""
    writer = csv.writer(handle, **_OUTPUT_DIALECT)
    writer.writerow(header)
    for row in rows:
        writer.writerow([null_literal if cell is None else cell for cell in row])
