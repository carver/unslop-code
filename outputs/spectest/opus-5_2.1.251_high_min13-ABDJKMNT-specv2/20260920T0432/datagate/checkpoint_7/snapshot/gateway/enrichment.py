"""Optional ingestion metadata: the `enrich=yes` flag and what it computes.

Enrichment is decided once, at ingestion, and the result is stored with the
dataset — so a query never recomputes it and a cached dataset remembers whether
it was enriched. `describe` produces exactly the fields the enriched query
response carries.
"""

from .formats import FILETYPE_CSV, Table
from .tabular import Cell

ENRICH = "enrich"
ENABLED = "yes"

TEXT = "text"
INTEGER = "integer"
FLOAT = "float"
NUMBER = "number"

# The label for a column holding exactly these cell types; anything else, and
# any column with no values at all, is text.
NUMERIC_LABELS = {frozenset({int}): INTEGER, frozenset({float}): FLOAT}


def enrichment_requested(args) -> bool:
    """Whether `args` asks for enrichment.

    Only a single, exact `enrich=yes` does: any other value, any repeat and an
    absent parameter all leave enrichment off, without being caller errors.
    """
    return args.getlist(ENRICH) == [ENABLED]


def describe(table: Table) -> dict:
    """The metadata fields an enriched dataset is served with.

    A workbook is summarised but not profiled: its columns carry the sheet's own
    types rather than parsed text, so per-column inference would describe the
    spreadsheet's formatting more than the data.
    """
    metadata = {
        "dataset_summary": {
            "filetype": table.filetype,
            "row_count": len(table.rows),
            "column_count": len(table.columns),
        }
    }
    if table.filetype == FILETYPE_CSV:
        metadata["column_details"] = _column_details(table.columns, table.rows)
    return metadata


def _column_details(columns: list[str], rows: list[list[Cell]]) -> dict:
    """One description per column, keyed by name.

    Columns are read in order, so a duplicated header name is described by the
    rightmost column carrying it — an object cannot hold the name twice.
    """
    return {
        name: _describe_column([row[index] for row in rows])
        for index, name in enumerate(columns)
    }


def _describe_column(values: list[Cell]) -> dict:
    """Type, distinct values and holes of one column.

    Only the values actually present are profiled: a blank is reported by
    `missing_count` alone, so it neither turns a numeric column into text nor
    counts as a distinct value of its own.
    """
    present = [value for value in values if not _is_missing(value)]
    return {
        "type": _column_type(present),
        "distinct_count": len(set(present)),
        "missing_count": len(values) - len(present),
    }


def _column_type(present: list[Cell]) -> str:
    """The label for a column's values: `integer`, `float`, `number` or `text`.

    Cells are typed when the table is parsed, so the column's label follows from
    the types present — whole numbers alone, fractions alone, the two mixed, and
    anything else.
    """
    kinds = {type(value) for value in present}
    if not present or str in kinds:
        return TEXT
    return NUMERIC_LABELS.get(frozenset(kinds), NUMBER)


def _is_missing(value: Cell) -> bool:
    """Whether a cell holds no value: empty, or nothing but whitespace."""
    return isinstance(value, str) and not value.strip()
