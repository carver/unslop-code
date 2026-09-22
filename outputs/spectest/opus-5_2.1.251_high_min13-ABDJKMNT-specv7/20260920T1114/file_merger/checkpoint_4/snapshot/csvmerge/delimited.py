"""Reading the two delimited text formats.

CSV follows the configurable dialect of checkpoint 1; TSV is tab separated and
unquoted, so a field containing a literal tab can only show up as a row wider
than the header and is rejected there (ambiguity T31).
"""

from __future__ import annotations

import csv
from typing import Iterator, TextIO

from csvmerge.dialect import CsvDialect
from csvmerge.errors import EXIT_INPUT, MergeError

Rows = Iterator[tuple[int, dict[str, object]]]


def read_csv(stream: TextIO, path: str, dialect: CsvDialect) -> tuple[list[str], Rows]:
    """Header and records of a CSV input, read under the configured dialect."""
    rows = csv.reader(
        stream,
        delimiter=",",
        quotechar=dialect.quotechar,
        escapechar=dialect.escapechar,
        doublequote=True,
    )
    header = next(rows, [])
    return header, _records(header, rows, dialect, path, reject_wide_rows=False)


def read_tsv(stream: TextIO, path: str, dialect: CsvDialect) -> tuple[list[str], Rows]:
    """Header and records of a TSV input; the header row is mandatory."""
    rows = csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None)
    header = next(rows, None)
    if header is None:
        raise MergeError(f"{path}: TSV input has no header row", EXIT_INPUT)
    return header, _records(header, rows, dialect, path, reject_wide_rows=True)


def _records(
    header: list[str],
    rows: Iterator[list[str]],
    dialect: CsvDialect,
    path: str,
    reject_wide_rows: bool,
) -> Rows:
    """Pair each non-blank row, and its line number, with the header names.

    Cells a short row does not reach read as null and, for CSV, surplus cells are
    dropped; a blank line carries no cells at all and is skipped.
    """
    for number, row in enumerate(rows, start=2):
        if not row:
            continue
        if reject_wide_rows and len(row) > len(header):
            raise MergeError(
                f"{path}:{number}: row has more fields than the header, "
                "which a literal tab inside a field would explain",
                EXIT_INPUT,
            )
        yield number, {
            name: None if index >= len(row) or dialect.is_null(row[index]) else row[index]
            for index, name in enumerate(header)
        }
