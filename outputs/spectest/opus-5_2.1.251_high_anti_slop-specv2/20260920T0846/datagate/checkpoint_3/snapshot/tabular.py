"""Decoding, delimiter detection and type inference for CSV payloads."""

import codecs
import csv
import io
import re
from collections import Counter

from errors import ApiError
from store import Row

# Longest BOMs first: the UTF-32 markers start with the UTF-16 ones.
BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

CANDIDATE_DELIMITERS = (",", ";", "\t", "|")
SAMPLE_LINES = 50
CONSISTENCY_RATIO = 0.9

INTEGER = re.compile(r"[+-]?\d+")
DECIMAL = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")


def decode(payload: bytes, charset: str | None = None) -> str:
    """Decode CSV bytes, honouring ``charset`` when the caller supplied one."""
    if charset is None:
        return _decode_detected(payload)
    try:
        return payload.decode(charset)
    except (LookupError, UnicodeDecodeError) as exc:
        raise ApiError(f"Cannot decode source using charset {charset!r}", 400) from exc


def _decode_detected(payload: bytes) -> str:
    """Use the encoding the bytes themselves prove; fall back to latin-1.

    A BOM names its encoding outright and UTF-8 is self-validating, so both are
    unambiguous. Anything else is guesswork, and latin-1 decodes every byte.
    """
    for bom, encoding in BOMS:
        if payload.startswith(bom):
            return payload.decode(encoding)
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("latin-1")


def detect_delimiter(text: str) -> str | None:
    """Return the delimiter that splits the sample into the widest stable table.

    A delimiter qualifies when most sampled lines yield the same number of
    fields and that number is greater than one; the widest such split wins.
    Returns ``None`` when no candidate describes a table.
    """
    sample = "\n".join(text.splitlines()[:SAMPLE_LINES])
    best_delimiter, best_width = None, 1
    for delimiter in CANDIDATE_DELIMITERS:
        rows = [row for row in csv.reader(io.StringIO(sample), delimiter=delimiter) if row]
        if not rows:
            continue
        width, hits = Counter(len(row) for row in rows).most_common(1)[0]
        if width > best_width and hits >= max(2, CONSISTENCY_RATIO * len(rows)):
            best_delimiter, best_width = delimiter, width
    return best_delimiter


def parse(text: str) -> tuple[list[str], list[Row]]:
    """Split a delimited payload into column names and typed data rows.

    Rows keep the 1-based number of the line they came from, counting the
    header as line one and counting blank lines even though they are dropped.
    """
    delimiter = detect_delimiter(text)
    if delimiter is None:
        raise ApiError("Source content is not tabular", 400)

    numbered = [
        (rowid, row)
        for rowid, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1)
        if any(field.strip() for field in row)
    ]
    if len(numbered) < 2:
        raise ApiError("Source needs a header row and at least one data row", 400)

    (_, header), *data = numbered
    columns = [name.strip() for name in header]
    return columns, [Row(rowid, _fit(row, len(columns))) for rowid, row in data]


def _fit(fields: list[str], width: int) -> list:
    """Type every field, squaring ragged rows off against the header width."""
    values = [infer_value(field) for field in fields[:width]]
    return values + [""] * (width - len(values))


def infer_value(field: str):
    """Turn numeric-looking text into a JSON number, leaving all else as text.

    Times (``08:30``), identifiers and anything else with non-numeric characters
    fail both patterns and keep their original spelling.
    """
    candidate = field.strip()
    if INTEGER.fullmatch(candidate):
        return int(candidate)
    if DECIMAL.fullmatch(candidate):
        return float(candidate)
    return field
