"""CSV rendering of a dataset page for ``GET /datasets/<id>/export``."""

import csv
import io

from flask.wrappers import Response

from gateway.values import Value

#: Sent without a charset parameter; the body itself is written as UTF-8.
CONTENT_TYPE = "text/csv"


def csv_response(
    identifier: str, columns: list[str], rows: list[list[Value]]
) -> Response:
    """Serve ``rows`` as a CSV file download named after the dataset."""
    return Response(
        render_csv(columns, rows),
        content_type=CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{identifier}.csv"'},
    )


def render_csv(columns: list[str], rows: list[list[Value]]) -> str:
    """Write the header and the rows as CSV text, in source column order."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()
