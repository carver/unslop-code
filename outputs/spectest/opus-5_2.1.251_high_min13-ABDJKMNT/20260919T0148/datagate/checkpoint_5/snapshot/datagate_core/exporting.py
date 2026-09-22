"""Serialising a page of a stored table as the CSV bytes `/export` downloads."""

import csv
import io

MEDIA_TYPE = "text/csv"


def csv_bytes(columns, rows):
    """Write `columns` as a header above `rows`, quoted per RFC 4180 and UTF-8 encoded.

    `csv.writer` renders the typed cells the store holds back into text, so an
    integer travels as `36` and a decimal as the literal its source carried.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def attachment_headers(identifier):
    """The download headers naming an export after its dataset."""
    return {
        "Content-Type": MEDIA_TYPE,
        "Content-Disposition": f'attachment; filename="{identifier}.csv"',
    }
