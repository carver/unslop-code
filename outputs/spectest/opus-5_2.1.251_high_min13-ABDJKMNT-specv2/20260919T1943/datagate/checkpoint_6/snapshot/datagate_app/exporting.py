"""Rendering a dataset query as CSV.

The export writes the header row followed by the same page of rows the JSON
endpoint would serve, in source column order. Values are the dataset's inferred
values (T36), written by the standard CSV writer, so quoting and escaping appear
only where the format requires them.
"""

import csv
from io import StringIO

from .controls import QueryControls
from .filtering import ColumnFilter
from .parsing import Dataset
from .results import select_page

CONTENT_TYPE = "text/csv"
ENCODING = "utf-8"
LINE_TERMINATOR = "\r\n"


def export_csv(dataset: Dataset, controls: QueryControls, filters: list[ColumnFilter]) -> bytes:
    """Write `dataset`'s header and the rows `controls`/`filters` select as CSV bytes."""
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator=LINE_TERMINATOR)
    writer.writerow(dataset.columns)
    writer.writerows(row.values for row in select_page(dataset, controls, filters))
    return buffer.getvalue().encode(ENCODING)
