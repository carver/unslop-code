"""Rendering a stored table into one response: sort, paginate, shape."""


def response_body(table, controls):
    """Build the success payload for a dataset request, apart from its timing."""
    body = {
        "ok": True,
        "columns": table.columns,
        "rows": _render(_page(table, controls), table.columns, controls),
    }
    if controls.show_total:
        body["total"] = len(table.rows)
    return body


def _page(table, controls):
    """Sort the rows, then cut the `_offset`/`_size` window out of the result.

    Rows travel as `(rowid, values)` pairs so that a row keeps the number of its
    source line however the request reorders or truncates the table.
    """
    numbered = list(enumerate(table.rows, start=1))
    if controls.sort_column is not None:
        position = table.columns.index(controls.sort_column)
        numbered.sort(key=lambda entry: _sort_key(entry[1][position]), reverse=controls.descending)
    return numbered[controls.offset : controls.offset + controls.size]


def _render(page, columns, controls):
    """Render a page as arrays (`_shape=lists`) or as objects (`_shape=objects`)."""
    if controls.shape == "lists":
        return [values for _, values in page]
    return [_object_row(rowid, values, columns, controls.show_rowid) for rowid, values in page]


def _object_row(rowid, values, columns, show_rowid):
    """Pair a row's values with their column names, keyed by column name."""
    row = dict(zip(columns, values))
    if show_rowid:
        # Written last so that a source column named `rowid` cannot displace the row number.
        row["rowid"] = rowid
    return row


def _sort_key(value):
    """Order numbers ahead of text, since type inference can leave a column mixed."""
    return (0, value) if isinstance(value, (int, float)) else (1, value)
