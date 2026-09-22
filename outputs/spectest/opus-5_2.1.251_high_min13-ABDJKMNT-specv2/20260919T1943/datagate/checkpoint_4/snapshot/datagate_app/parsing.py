"""Table building: CSV delimiter inference, tabular validation and row typing.

Every source kind ends up in `build_table`, which is what makes a spreadsheet and
a CSV of the same table produce the same `Dataset`.
"""

import csv
from dataclasses import dataclass
from io import StringIO
from itertools import islice
from typing import Any

from .errors import DataGateError
from .values import coerce_value

# Ordered by preference; ties during inference resolve to the earliest entry.
DELIMITERS = (",", ";", "\t", "|")
SNIFF_ROWS = 50

_NON_TABULAR_CONTENT_TYPES = ("text/html", "application/xml", "text/xml", "application/json")
_MARKUP_PREFIXES = ("<", "{", "[")


@dataclass(frozen=True)
class Row:
    """One data row: its typed cells and the source-file row it was read from."""

    rowid: int
    values: list[Any]


@dataclass(frozen=True)
class Dataset:
    """A parsed table: header names plus every data row, in source order."""

    columns: list[str]
    rows: list[Row]


def reject_non_tabular(content_type: str, text: str) -> None:
    """Fail fast on payloads that are documents rather than tables."""
    declared = content_type.split(";")[0].strip().lower()
    if declared in _NON_TABULAR_CONTENT_TYPES:
        raise DataGateError(f"Source is {declared}, not tabular content", 400)
    stripped = text.lstrip()
    if not stripped:
        raise DataGateError("Source is empty", 400)
    if stripped.startswith(_MARKUP_PREFIXES) or "\x00" in text:
        raise DataGateError("Source is not tabular content", 400)


def infer_delimiter(text: str) -> str:
    """Pick the candidate delimiter that yields the most consistent table."""
    best_score = (0.0, 1)
    best_delimiter = DELIMITERS[0]
    for delimiter in DELIMITERS:
        widths = [len(row) for row in _read_rows(text, delimiter, SNIFF_ROWS) if row]
        if not widths or widths[0] < 2:
            continue
        score = (widths.count(widths[0]) / len(widths), widths[0])
        if score > best_score:
            best_score, best_delimiter = score, delimiter
    return best_delimiter


def parse_table(text: str) -> Dataset:
    """Parse CSV `text` into a `Dataset` over its inferred delimiter."""
    return build_table(_read_rows(text, infer_delimiter(text)))


def build_table(grid: list[list[str]]) -> Dataset:
    """Turn a grid of text cells into a `Dataset`, header row first.

    Rows are numbered from 1 as they appear in the source, so blank rows that are
    dropped here still consume the row number they occupied (T26, T46).
    """
    numbered = [(number, row) for number, row in enumerate(grid, start=1) if any(cell.strip() for cell in row)]
    if len(numbered) < 2:
        raise DataGateError("A valid table needs a header row and at least one data row", 400)
    columns = [cell.strip() for cell in numbered[0][1]]
    return Dataset(columns, [Row(number, _build_row(row, len(columns))) for number, row in numbered[1:]])


def _read_rows(text: str, delimiter: str, limit: int | None = None) -> list[list[str]]:
    reader = csv.reader(StringIO(text), delimiter=delimiter)
    return list(islice(reader, limit))


def _build_row(row: list[str], width: int) -> list[Any]:
    """Align a row with the header, then type each cell."""
    aligned = (row + [""] * width)[:width]
    return [coerce_value(cell) for cell in aligned]
