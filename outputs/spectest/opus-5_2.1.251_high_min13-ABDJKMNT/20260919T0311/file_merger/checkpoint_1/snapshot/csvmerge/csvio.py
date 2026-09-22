"""CSV input parsing and the fixed output dialect."""
from __future__ import annotations

import csv
import sys
from contextlib import contextmanager
from typing import Iterable, Iterator, Sequence

#: The output dialect is deterministic and independent of the input flags.
_WRITER_DIALECT = {
    "delimiter": ",",
    "quotechar": '"',
    "doublequote": True,
    "escapechar": None,
    "lineterminator": "\n",
    "quoting": csv.QUOTE_MINIMAL,
}


def reader_dialect(quotechar: str, escapechar: str | None) -> dict:
    """csv.reader keyword arguments for the input files."""
    return {
        "delimiter": ",",
        "quotechar": quotechar,
        "escapechar": escapechar,
        "doublequote": True,
    }


@contextmanager
def open_table(path: str, dialect: dict) -> Iterator[tuple[list[str], Iterator[list[str]]]]:
    """Open one input and yield its header row and an iterator over its data rows.

    `utf-8-sig` reads plain UTF-8 unchanged while tolerating a leading BOM.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = csv.reader(handle, **dialect)
        yield next(rows, []), rows


@contextmanager
def open_output(path: str):
    """Open the output sink; `-` means stdout."""
    if path == "-":
        sys.stdout.reconfigure(newline="")
        yield sys.stdout
    else:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            yield handle


def write_rows(stream, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    """Write the header and every row in the canonical output dialect."""
    writer = csv.writer(stream, **_WRITER_DIALECT)
    writer.writerow(header)
    writer.writerows(rows)
