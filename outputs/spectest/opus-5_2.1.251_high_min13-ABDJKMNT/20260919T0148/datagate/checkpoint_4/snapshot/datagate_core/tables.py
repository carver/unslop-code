"""Shaping parsed records into a rectangular header-plus-rows table."""

from .errors import DatagateError


def split_header(records, source):
    """Split `records` into header names and rows squared to the header's width.

    `source` names the origin of the records ("a CSV file", "the first worksheet")
    so the 400 raised for a table without a header and a data row says which one.
    """
    if len(records) < 2:
        raise DatagateError(
            400, f"Non-tabular content: {source} needs a header row and at least one data row."
        )

    columns = records[0]
    return columns, [_square(record, len(columns)) for record in records[1:]]


def _square(record, width):
    """Pad a short record with empty cells and drop cells beyond the header width."""
    return (record + [""] * width)[:width]
