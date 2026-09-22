"""Choosing how to read incoming bytes - workbook or text CSV - into a `Table`."""

from datagate_core.decoding import decode
from datagate_core.spreadsheets import is_workbook, read_first_sheet
from datagate_core.tables import Table, build_table, parse_table


def ingest(data: bytes, charset: str | None) -> Table:
    """Read `data` in whichever supported format it is written in.

    The format is taken from the bytes themselves, not from a file name or URL
    (T35), so `charset` is only consulted for text CSV sources (T36).
    """
    if is_workbook(data):
        return build_table(read_first_sheet(data))
    return parse_table(decode(data, charset))
