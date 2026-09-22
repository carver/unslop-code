"""CSV parsing: delimiter inference, tabular validation and row building."""

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
class Dataset:
    """A parsed table: header names plus every data row, in source order."""

    columns: list[str]
    rows: list[list[Any]]


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
    """Parse `text` into a `Dataset`, requiring a header row and a data row."""
    rows = [row for row in _read_rows(text, infer_delimiter(text)) if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise DataGateError("A valid CSV needs a header row and at least one data row", 400)
    columns = [cell.strip() for cell in rows[0]]
    return Dataset(columns, [_build_row(row, len(columns)) for row in rows[1:]])


def _read_rows(text: str, delimiter: str, limit: int | None = None) -> list[list[str]]:
    reader = csv.reader(StringIO(text), delimiter=delimiter)
    return list(islice(reader, limit))


def _build_row(row: list[str], width: int) -> list[Any]:
    """Align a row with the header, then type each cell."""
    aligned = (row + [""] * width)[:width]
    return [coerce_value(cell) for cell in aligned]
