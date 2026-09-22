"""CSV rendering of a dataset page, served as a file attachment."""

import csv
import io

from flask import Response

from store import Row

# Stated without a charset parameter so the header reads exactly `text/csv`; the body is UTF-8.
CSV_CONTENT_TYPE = "text/csv"


def csv_response(dataset_id: str, columns: list[str], rows: list[Row]) -> Response:
    """Render the header and the selected rows as a CSV download named after the dataset."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return Response(
        buffer.getvalue().encode("utf-8"),
        content_type=CSV_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{dataset_id}.csv"'},
    )
