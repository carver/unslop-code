"""Decoding and parsing of CSV bytes into a header row plus typed data rows."""

import csv
import io

from charset_normalizer import from_bytes

from .errors import DataGateError
from .values import Value, coerce

DELIMITERS = (",", ";", "\t")

Table = tuple[list[str], list[list[Value]]]


def decode(data: bytes, charset: str | None) -> str:
    """Decode ``data`` with ``charset`` when given, else with the detected encoding."""
    if charset is None:
        detected = from_bytes(data).best()
        if detected is None:
            raise DataGateError("source content could not be decoded as text", 400)
        text = str(detected)
    else:
        try:
            text = data.decode(charset)
        except (LookupError, UnicodeDecodeError) as exc:
            raise DataGateError(
                f"unsupported or malformed charset {charset!r}: {exc}", 400
            ) from exc
    return text.removeprefix("\ufeff")


def _read_rows(text: str, delimiter: str) -> list[list[str]]:
    """Split ``text`` on ``delimiter``, dropping blank lines."""
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [row for row in reader if any(cell.strip() for cell in row)]


def _shape_score(rows: list[list[str]]) -> tuple[float, int]:
    """Rank a candidate parse by how many rows match the header width, then by width.

    A parse without a header row, without a data row or without at least two columns
    scores zero, which marks the content as non-tabular for that delimiter.
    """
    if len(rows) < 2 or len(rows[0]) < 2:
        return (0.0, 0)
    width = len(rows[0])
    aligned = sum(1 for row in rows[1:] if len(row) == width)
    return (aligned / (len(rows) - 1), width)


def _fit(row: list[str], width: int) -> list[Value]:
    """Coerce a data row to JSON values and square it off to ``width`` columns."""
    cells = [coerce(cell) for cell in row[:width]]
    return cells + [""] * (width - len(cells))


def parse_table(data: bytes, charset: str | None) -> Table:
    """Turn remote CSV bytes into ``(columns, rows)`` in source column order.

    The delimiter is inferred by parsing the text with every supported candidate and
    keeping the one that yields the most consistent table; ties favour ``,`` then ``;``
    then tab, so the same bytes always produce the same table.
    """
    text = decode(data, charset)
    if "\x00" in text:
        raise DataGateError("source content is not tabular", 400)

    parses = {delimiter: _read_rows(text, delimiter) for delimiter in DELIMITERS}
    scores = {delimiter: _shape_score(rows) for delimiter, rows in parses.items()}
    delimiter = max(DELIMITERS, key=scores.__getitem__)
    _, width = scores[delimiter]
    if width == 0:
        raise DataGateError(
            "source content is not tabular: expected a delimited header row and at "
            "least one data row",
            400,
        )

    rows = parses[delimiter]
    columns = [cell.strip() for cell in rows[0]]
    return columns, [_fit(row, width) for row in rows[1:]]
