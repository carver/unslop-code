"""Recognising an ingested file's format and parsing it into a table.

CSV, `.xls` and `.xlsx` all reduce to the same columns-and-rows model, so the
routes ingest bytes through here and never learn which format they were given —
except by the `filetype` the table reports, which enrichment names.
"""

from dataclasses import dataclass

from .decoding import decode_bytes
from .spreadsheets import workbook_reader
from .tabular import Cell, parse_table, shape_table

FILETYPE_CSV = "csv"
FILETYPE_EXCEL = "excel"


@dataclass(frozen=True)
class Table:
    """A parsed file: the format it was in, its columns and its typed rows."""

    filetype: str
    columns: list[str]
    rows: list[list[Cell]]


def build_table(raw: bytes, charset: str | None) -> Table:
    """Parse `raw` into a table, whichever format it is in.

    `charset` describes text, so a workbook ignores it entirely — an unusable
    codec name is only an error for a CSV source. Bytes that are neither a
    workbook nor tabular text are refused by the CSV parser as unrecognised.
    """
    reader = workbook_reader(raw)
    if reader is None:
        return Table(FILETYPE_CSV, *parse_table(decode_bytes(raw, charset)))
    return Table(FILETYPE_EXCEL, *shape_table(reader(raw)))
