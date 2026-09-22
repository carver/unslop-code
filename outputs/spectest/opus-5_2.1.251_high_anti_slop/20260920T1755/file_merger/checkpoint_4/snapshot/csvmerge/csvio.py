"""The CSV dialect shared by input and output, and writing the result."""

from __future__ import annotations

import csv
import io
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence, TextIO

STDOUT_TARGET = "-"


@dataclass(frozen=True)
class InputDialect:
    """How CSV cells are quoted, escaped and spelled when null.

    CSV is comma separated UTF-8 with a header row; only the quoting details
    and the null spelling are configurable, and the same settings are used
    again when the merged result is written.
    """

    quotechar: str = '"'
    escapechar: str | None = None
    null_literal: str = ""

    def csv_args(self) -> dict:
        return {
            "delimiter": ",",
            "quotechar": self.quotechar,
            "escapechar": self.escapechar,
            "doublequote": self.escapechar is None,
            "lineterminator": "\n",
        }

    def is_null(self, text: str | None) -> bool:
        return text is None or text == "" or text == self.null_literal


class RowFormatter:
    """Renders rows as CSV text, so their size on disk is known before writing.

    Cutting a file at a byte limit needs the encoded length of a row up
    front, which only the CSV writer can give; one writer over a reused
    buffer serves every row.
    """

    def __init__(self, dialect: InputDialect) -> None:
        self._buffer = io.StringIO()
        self._writer = csv.writer(self._buffer, **dialect.csv_args())

    def line(self, cells: Sequence[Any]) -> str:
        """Return ``cells`` as one CSV line, line terminator included."""
        self._buffer.seek(0)
        self._buffer.truncate()
        self._writer.writerow(cells)
        return self._buffer.getvalue()


def write_csv(path: str, header: Sequence[str], rows: Iterable[Sequence[Any]], dialect: InputDialect) -> None:
    """Write the header and rows to a file, or to stdout for ``-``."""
    with _open_output(path) as stream:
        writer = csv.writer(stream, **dialect.csv_args())
        writer.writerow(header)
        writer.writerows(rows)


@contextmanager
def _open_output(path: str) -> Iterator[TextIO]:
    """Yield the output stream, replacing a target file only once it is complete."""
    if path == STDOUT_TARGET:
        yield sys.stdout
        return
    target = Path(path)
    partial = target.with_name(f".{target.name}.partial")
    try:
        with partial.open("w", encoding="utf-8", newline="") as handle:
            yield handle
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
