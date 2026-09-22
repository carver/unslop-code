"""CSV parsing: delimiter inference, table shape and cell typing."""

import csv
import io
import math
import re

from .errors import ApiError

DELIMITERS = (",", ";", "\t")
# Bodies opening with these are markup or JSON documents, never CSV.
MARKUP_PREFIXES = ("<", "{", "[")

INTEGER = re.compile(r"[+-]?\d+")
DECIMAL = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")

Cell = str | int | float


def parse_table(text: str) -> tuple[list[str], list[list[Cell]]]:
    """Parse decoded CSV text into its column names and typed rows.

    The first record is the header; every later record is squared off to the
    header's width so that rows stay aligned with `columns`.
    """
    text = text.lstrip("\ufeff")
    _reject_non_tabular(text)
    records = _read_records(text, infer_delimiter(text))
    if len(records) < 2:
        raise ApiError(400, "csv needs at least one header row and one data row")

    columns = records[0]
    rows = [_align(record, len(columns)) for record in records[1:]]
    return columns, rows


def infer_delimiter(text: str) -> str:
    """Pick the delimiter that splits the content into the most consistent table.

    Candidates are scored by how many records match the header's field count and
    then by how many fields that header has; ties keep `DELIMITERS` order. A
    candidate that leaves the header as a single field is no delimiter at all.
    """
    best_score, best_delimiter = None, None
    for delimiter in DELIMITERS:
        records = _read_records(text, delimiter)
        width = len(records[0]) if records else 0
        if width < 2:
            continue
        score = (sum(len(r) == width for r in records[1:]), width)
        if best_score is None or score > best_score:
            best_score, best_delimiter = score, delimiter

    if best_delimiter is None:
        raise ApiError(400, "content is not tabular: no ',', ';' or tab delimiter found")
    return best_delimiter


def coerce(value: str) -> Cell:
    """Type a single cell: integer and decimal literals become JSON numbers.

    Anything else — including time-like values such as `08:30` and spellings
    Python would accept but JSON has no room for (`1_000`, `nan`, `inf`) — stays
    text, exactly as it appeared in the source.
    """
    literal = value.strip()
    if INTEGER.fullmatch(literal):
        return int(literal)
    if DECIMAL.fullmatch(literal):
        number = float(literal)
        return number if math.isfinite(number) else value
    return value


def _read_records(text: str, delimiter: str) -> list[list[str]]:
    """Read `text` as CSV, dropping records that hold no content at all."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return [record for record in reader if any(field.strip() for field in record)]


def _align(record: list[str], width: int) -> list[Cell]:
    """Pad a short record with empty cells and drop fields past the header."""
    padded = record + [""] * (width - len(record))
    return [coerce(field) for field in padded[:width]]


def _reject_non_tabular(text: str) -> None:
    stripped = text.strip()
    if not stripped:
        raise ApiError(400, "content is empty")
    if stripped[0] in MARKUP_PREFIXES:
        raise ApiError(400, "content is markup or json, not tabular data")
    if "\x00" in text:
        raise ApiError(400, "content is binary, not tabular data")
