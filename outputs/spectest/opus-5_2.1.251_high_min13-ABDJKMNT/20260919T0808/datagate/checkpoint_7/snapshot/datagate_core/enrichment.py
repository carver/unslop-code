"""Optional ingestion enrichment: the `enrich` flag and the metadata it computes.

The metadata describes a dataset as it was ingested rather than the page a
later query asks for (T80), so it is computed once, here, and stored beside the
table.
"""

from werkzeug.datastructures import MultiDict

from datagate_core.tables import Table
from datagate_core.values import Value

ENRICH_PARAMETER = "enrich"
ENRICH_VALUE = "yes"

#: The `filetype` a summary reports, one per reader (T74).
CSV = "csv"
EXCEL = "excel"

#: Column type labels.
INTEGER, FLOAT, NUMBER, TEXT = "integer", "float", "number", "text"


def wants_enrichment(args: MultiDict) -> bool:
    """Whether a `/convert` request asked for enrichment.

    Only the exact value `yes` turns it on; every other state - a different
    case, a truthy synonym, an empty or absent value - leaves enrichment off
    rather than failing (T73).
    """
    return args.get(ENRICH_PARAMETER) == ENRICH_VALUE


def describe(table: Table, filetype: str) -> dict:
    """The metadata an enriched ingestion stores beside `table`.

    Spreadsheets carry the summary alone; the per-column details are a CSV
    feature (T75).
    """
    summary = {
        "filetype": filetype,
        "row_count": len(table.rows),
        "column_count": len(table.columns),
    }
    if filetype == EXCEL:
        return {"dataset_summary": summary}
    return {"dataset_summary": summary, "column_details": _column_details(table)}


def _column_details(table: Table) -> dict:
    """One entry per column, keyed by name; a repeated name keeps the later column (T81)."""
    return {
        name: _details([row[index] for row in table.rows])
        for index, name in enumerate(table.columns)
    }


def _details(cells: list[Value]) -> dict:
    """Describe one column, blank cells being the missing values it is short of (T77)."""
    present = [cell for cell in cells if not _is_blank(cell)]
    return {
        "type": _type_label(present),
        "distinct_count": len(set(present)),
        "missing_count": len(cells) - len(present),
    }


def _is_blank(cell: Value) -> bool:
    """Whether a cell holds no value: empty, or nothing but space."""
    return isinstance(cell, str) and not cell.strip()


def _type_label(values: list[Value]) -> str:
    """Label a column by the types its present values were inferred at (T76).

    A column that mixes whole and decimal numbers is `number`; one holding any
    text at all - or holding nothing - is `text`.
    """
    kinds = {type(value) for value in values}
    if kinds == {int}:
        return INTEGER
    if kinds == {float}:
        return FLOAT
    if kinds == {int, float}:
        return NUMBER
    return TEXT
