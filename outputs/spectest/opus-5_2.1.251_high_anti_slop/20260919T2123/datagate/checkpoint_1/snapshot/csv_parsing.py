"""Decoding, delimiter inference and type inference for CSV payloads."""

import codecs
import csv
import io
import re
from collections import Counter

from charset_normalizer import from_bytes

from errors import DatagateError

CANDIDATE_DELIMITERS = (",", ";", "\t")
FALLBACK_ENCODINGS = ("cp1252", "latin-1")
BOM = "\ufeff"
SAMPLE_LINES = 20
CONSISTENCY_THRESHOLD = 0.9

TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
DECIMAL_PATTERN = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")


def decode_with(data: bytes, charset: str) -> str:
    """Decode with a caller-supplied charset, which is authoritative and must fit the bytes."""
    try:
        codec = codecs.lookup(charset)
    except LookupError as exc:
        raise DatagateError(400, f"Unsupported charset: {charset!r}") from exc
    try:
        return data.decode(codec.name).lstrip(BOM)
    except UnicodeDecodeError as exc:
        raise DatagateError(400, f"Source content is not valid {charset!r} text") from exc


def decode_candidates(data: bytes) -> list[str]:
    """Decode the payload every plausible way, in preference order.

    UTF-8 comes first because it validates itself, then the detector's guesses, then the
    Western single-byte codecs: detection is unreliable on short samples and readily mistakes
    single-byte text for a multi-byte codec, which would hide the delimiter. Latin-1 accepts
    any byte sequence, so the list is never empty.
    """
    encodings = ["utf-8", *(match.encoding for match in from_bytes(data)), *FALLBACK_ENCODINGS]
    texts = []
    for encoding in dict.fromkeys(encodings):
        try:
            texts.append(data.decode(encoding).lstrip(BOM))
        except UnicodeDecodeError:
            continue
    return texts


def detect_delimiter(text: str) -> str | None:
    """Pick the candidate delimiter that splits the sample into a stable, multi-column grid.

    Returns None when no candidate produces one, which is how non-tabular content is recognised.
    """
    sample = "\n".join(text.splitlines()[:SAMPLE_LINES])
    layouts = {delimiter: _dominant_layout(sample, delimiter) for delimiter in CANDIDATE_DELIMITERS}
    usable = [
        delimiter
        for delimiter, (width, consistency) in layouts.items()
        if width > 1 and consistency >= CONSISTENCY_THRESHOLD
    ]
    if not usable:
        return None
    return max(usable, key=lambda delimiter: layouts[delimiter][0])


def _dominant_layout(sample: str, delimiter: str) -> tuple[int, float]:
    """Return the most common field count for a delimiter and the share of rows that match it."""
    widths = Counter(len(row) for row in csv.reader(io.StringIO(sample), delimiter=delimiter) if row)
    width, matching = widths.most_common(1)[0]
    return width, matching / widths.total()


def infer_value(cell: str) -> str | int | float:
    """Convert a cell to a number when it is unambiguously numeric; anything else stays text.

    Time-like values such as ``08:30`` are checked first so they are never split into numbers.
    """
    text = cell.strip()
    if TIME_PATTERN.match(text):
        return text
    if INTEGER_PATTERN.match(text):
        return int(text)
    if DECIMAL_PATTERN.match(text):
        return float(text)
    return text


def read_grid(data: bytes, charset: str | None) -> tuple[str, str]:
    """Return the decoded text and its delimiter, choosing the decoding that reads as a table."""
    candidates = [decode_with(data, charset)] if charset else decode_candidates(data)
    for text in candidates:
        delimiter = detect_delimiter(text)
        if delimiter is not None:
            return text, delimiter
    raise DatagateError(400, "Source content is not tabular: no CSV delimiter could be inferred")


def parse_table(data: bytes, charset: str | None) -> tuple[list[str], list[list]]:
    """Parse the payload into header names and typed rows, preserving source column order."""
    if not data.strip():
        raise DatagateError(400, "Source content is empty")
    text, delimiter = read_grid(data, charset)

    rows = [
        row
        for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        if any(cell.strip() for cell in row)
    ]
    if len(rows) < 2:
        raise DatagateError(400, "Source content needs a header row and at least one data row")

    columns = [cell.strip() for cell in rows[0]]
    return columns, [_typed_row(row, len(columns)) for row in rows[1:]]


def _typed_row(row: list[str], width: int) -> list:
    """Fit a row to the header width, padding short rows and dropping surplus cells."""
    cells = row[:width] + [""] * (width - len(row))
    return [infer_value(cell) for cell in cells]
