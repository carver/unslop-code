"""Recognising an ingested file's format and parsing it into a table.

CSV, `.xls` and `.xlsx` all reduce to the same columns-and-rows model, so the
routes ingest bytes through here and never learn which format they were given.
"""

from .decoding import decode_bytes
from .spreadsheets import workbook_reader
from .tabular import Cell, parse_table, shape_table


def build_table(raw: bytes, charset: str | None) -> tuple[list[str], list[list[Cell]]]:
    """Parse `raw` into its columns and rows, whichever format it is in.

    `charset` describes text, so a workbook ignores it entirely — an unusable
    codec name is only an error for a CSV source. Bytes that are neither a
    workbook nor tabular text are refused by the CSV parser as unrecognised.
    """
    reader = workbook_reader(raw)
    if reader is None:
        return parse_table(decode_bytes(raw, charset))
    return shape_table(reader(raw))
