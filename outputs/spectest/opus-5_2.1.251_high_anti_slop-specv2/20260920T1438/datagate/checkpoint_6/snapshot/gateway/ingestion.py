"""Turning a raw payload into a table, whatever format it arrived in."""

from gateway.errors import GateError
from gateway.parsing import decode_payload, parse_csv
from gateway.spreadsheets import is_workbook, read_sheet


def build_table(
    payload: bytes, charset: str | None
) -> tuple[list[str], list[list[str]]]:
    """Read ``payload`` as CSV, ``.xls`` or ``.xlsx`` into a header and its rows.

    ``charset`` describes text CSV only: a workbook carries its own encoding,
    so an unusable charset is not held against one.
    """
    if is_workbook(payload):
        return as_table(read_sheet(payload))
    return as_table(parse_csv(decode_payload(payload, charset)))


def as_table(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """Split parsed rows into their header and data rows.

    A source is only tabular once it holds a header naming at least one
    column and at least one row of data under it.
    """
    if len(rows) < 2:
        raise GateError("Source needs a header row and at least one data row", 400)

    header, *data = rows
    if not any(name.strip() for name in header):
        raise GateError("Source content has no usable header row", 400)
    return header, data
