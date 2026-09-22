"""Ingestion enrichment: the metadata `enrich=yes` computes and stores with a dataset."""

from .formats import Format

ENRICH = "enrich"
ENABLED = "yes"

# `.xls` and `.xlsx` are both reported as one spreadsheet filetype, since the spec
# names `excel` for either container (AMBIGUITIES T75).
FILETYPES = {Format.CSV: "csv", Format.XLS: "excel", Format.XLSX: "excel"}

TEXT = "text"
MIXED_NUMBER = "number"


def enrich_requested(args):
    """True only for the exact value `yes`; every other state leaves enrichment off.

    The first value decides when the parameter is repeated (AMBIGUITIES T74).
    """
    return args.get(ENRICH) == ENABLED


def build_metadata(detected, columns, rows):
    """Describe a freshly parsed table as the metadata an enriched query reports.

    Workbooks are summarised but not profiled: the spec asks for `dataset_summary`
    alone there (AMBIGUITIES T79).
    """
    summary = {
        "filetype": FILETYPES[detected],
        "row_count": len(rows),
        "column_count": len(columns),
    }
    if detected is not Format.CSV:
        return {"dataset_summary": summary}
    return {"dataset_summary": summary, "column_details": _column_details(columns, rows)}


def _column_details(columns, rows):
    """Profile each column of a CSV table, keyed by its header name."""
    return {name: _profile([row[index] for row in rows]) for index, name in enumerate(columns)}


def _profile(values):
    """The type, distinct count and missing count of one column's cells.

    Blank cells are counted as missing rather than as a value, so they reach
    neither the distinct count nor the type (AMBIGUITIES T77, T78).
    """
    present = [value for value in values if not _is_missing(value)]
    return {
        "type": _type_label(present),
        "distinct_count": len(set(present)),
        "missing_count": len(values) - len(present),
    }


def _is_missing(value):
    """True for a cell holding no content: an empty or whitespace-only string."""
    return isinstance(value, str) and not value.strip()


def _type_label(values):
    """Label a column from the types ingestion inferred for its present cells.

    A column whose cells are all whole numbers is `integer` and one of decimals is
    `float`; a numeric column holding both is the generic `number`. Anything with a
    word in it -- and a column with nothing to judge -- is `text`.
    """
    if not values or any(isinstance(value, str) for value in values):
        return TEXT

    kinds = {"integer" if isinstance(value, int) else "float" for value in values}
    return kinds.pop() if len(kinds) == 1 else MIXED_NUMBER
