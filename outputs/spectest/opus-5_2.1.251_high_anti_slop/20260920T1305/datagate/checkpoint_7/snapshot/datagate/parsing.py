"""Decoding of source bytes and their parsing into a header row plus typed data rows.

A source is read as a spreadsheet when its bytes carry an ``.xlsx`` or ``.xls`` file
signature, and as delimited text otherwise; ``charset`` only applies to the latter.
"""

import csv
import io

from charset_normalizer import from_bytes

from .errors import DataGateError
from .spreadsheets import looks_like_spreadsheet, read_workbook
from .tables import CSV, Table, build_table

DELIMITERS = (",", ";", "\t")


def parse_source(data: bytes, charset: str | None) -> Table:
    """Turn source bytes into a ``Table``, picking the reader by file signature.

    Bytes in no recognised format, and bytes whose table has no header row or no data
    row, raise a 400 error.
    """
    if looks_like_spreadsheet(data):
        return read_workbook(data)
    return parse_csv(data, charset)


def decode(data: bytes, charset: str | None) -> str:
    """Decode ``data`` with ``charset`` when given, else with the detected encoding."""
    if charset is None:
        detected = from_bytes(data).best()
        if detected is None:
            raise DataGateError(
                "source is in no supported format: neither a spreadsheet nor text "
                "in a recognisable encoding",
                400,
            )
        text = str(detected)
    else:
        try:
            text = data.decode(charset)
        except (LookupError, UnicodeDecodeError) as exc:
            raise DataGateError(
                f"unsupported or malformed charset {charset!r}: {exc}", 400
            ) from exc
    return text.removeprefix("\ufeff")


def parse_csv(data: bytes, charset: str | None) -> Table:
    """Turn delimited text bytes into a ``Table`` in source column order.

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
    if scores[delimiter] == (0.0, 0):
        raise DataGateError(
            "source content is not tabular: expected a delimited header row and at "
            "least one data row",
            400,
        )
    return build_table(parses[delimiter], CSV)


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
