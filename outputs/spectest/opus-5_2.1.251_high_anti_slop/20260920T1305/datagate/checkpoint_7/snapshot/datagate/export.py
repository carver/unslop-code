"""Rendering a dataset's selected rows back out as a CSV document."""

import csv
import io

from .values import Value


def render_csv(columns: list[str], rows: list[list[Value]]) -> str:
    """Return a CSV document holding ``columns`` as its header row, then ``rows``.

    Cells are written in source column order and quoted only where a delimiter, quote
    or line break would otherwise make the document ambiguous.
    """
    document = io.StringIO()
    writer = csv.writer(document)
    writer.writerow(columns)
    writer.writerows(rows)
    return document.getvalue()
