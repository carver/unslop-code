"""Rendering a page of a dataset as a downloadable CSV attachment."""

import csv
import io

from flask import Response

from datagate_core.tables import NumberedRow
from datagate_core.values import as_text


def csv_attachment(dataset_id: str, columns: list[str], page: list[NumberedRow]) -> Response:
    """The `/export` response: the page as CSV, downloaded as `<dataset-id>.csv`."""
    return Response(
        to_csv(columns, page).encode("utf-8"),
        # Spelled out rather than left to Flask's mimetype default, which would
        # append a charset the spec's `Content-Type` does not name (T40).
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{dataset_id}.csv"'},
    )


def to_csv(columns: list[str], page: list[NumberedRow]) -> str:
    """Write the header row and then the page's cells as RFC 4180 CSV text.

    Cells are written in their stored, type-inferred form (T45); `rowid` is not
    a source column and so never appears.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows([as_text(cell) for cell in row] for _, row in page)
    return buffer.getvalue()
