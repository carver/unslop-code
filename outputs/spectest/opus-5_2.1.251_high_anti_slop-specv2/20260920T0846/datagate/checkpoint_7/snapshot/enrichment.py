"""Optional ingestion enrichment: the ``/convert`` trigger and the metadata it computes.

An enriched conversion stores a description of the table beside its rows, which
the dataset route then reports. The description is derived from the ingested
table, so it always describes the bytes the stored rows were read from.
"""

from werkzeug.datastructures import MultiDict

from sheets import looks_like_workbook
from store import Row

ENRICH = "enrich"
ENABLED = "yes"

CSV, EXCEL = "csv", "excel"
TEXT, NUMBER, INTEGER, FLOAT = "text", "number", "integer", "float"


def enrich_requested(args: MultiDict) -> bool:
    """Report whether a conversion asks for enrichment.

    Enrichment is opt-in through one exact ``enrich=yes``; every other
    spelling, and a repeated parameter, simply leaves it switched off.
    """
    return args.getlist(ENRICH) == [ENABLED]


def describe(payload: bytes, columns: list[str], rows: list[Row]) -> dict:
    """Describe an ingested table as the fields a dataset response carries.

    Every table is summarised as a whole, and a delimited one is profiled
    column by column on top of that. The payload decides which of the two it
    is, the same way the ingestion itself did.
    """
    filetype = EXCEL if looks_like_workbook(payload) else CSV
    summary = {
        "filetype": filetype,
        "row_count": len(rows),
        "column_count": len(columns),
    }
    if filetype == EXCEL:
        return {"dataset_summary": summary}
    return {
        "dataset_summary": summary,
        "column_details": {
            name: _profile([row.values[index] for row in rows])
            for index, name in enumerate(columns)
        },
    }


def _profile(values: list) -> dict:
    """Profile one column: what it holds, how varied it is and what it lacks.

    Blank cells are the column's missing values, so they are counted on their
    own and left out of both the distinct count and the type.
    """
    present = [value for value in values if not _is_missing(value)]
    return {
        "type": _column_type(present),
        "distinct_count": len(set(present)),
        "missing_count": len(values) - len(present),
    }


def _is_missing(value) -> bool:
    """Report whether a cell holds nothing: empty or whitespace-only text."""
    return isinstance(value, str) and not value.strip()


def _column_type(values: list) -> str:
    """Label a column by the types its present values carry.

    Whole and fractional numbers name themselves; a column holding both is
    numeric without being either, and anything with text in it is text. An
    entirely blank column has nothing to go on and reads as text.
    """
    kinds = {type(value) for value in values}
    if not kinds or kinds - {int, float}:
        return TEXT
    if kinds == {int}:
        return INTEGER
    if kinds == {float}:
        return FLOAT
    return NUMBER
