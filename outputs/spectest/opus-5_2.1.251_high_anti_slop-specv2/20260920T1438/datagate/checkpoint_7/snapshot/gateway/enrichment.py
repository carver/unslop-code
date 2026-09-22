"""Optional ingestion-time description of a dataset: its shape and its columns.

Enrichment is asked for once, on ``/convert``, and computed while the source is
being ingested. What it produces is stored with the dataset and answered with
every read of it, so describing a table never costs a reader anything.
"""

from werkzeug.datastructures import MultiDict

from gateway.ingestion import EXCEL
from gateway.values import Value

#: Metadata fields a dataset carries when it was ingested with enrichment.
Metadata = dict[str, dict]

#: Query parameter asking ``/convert`` for enrichment, and its only value.
ENRICH = "enrich"
ENABLED = "yes"

#: Column type labels reported in ``column_details``.
TEXT, NUMBER, INTEGER, FLOAT = "text", "number", "integer", "float"

#: Cell standing for no value at all, in a source that left it blank.
MISSING = ""


def enrichment_requested(args: MultiDict) -> bool:
    """Report whether a request asks for enrichment with a single ``enrich=yes``.

    Nothing else turns enrichment on: another value, a bare flag or a repeated
    parameter all ingest as usual rather than failing the request.
    """
    return args.getlist(ENRICH) == [ENABLED]


def describe(filetype: str, columns: list[str], rows: list[list[Value]]) -> Metadata:
    """Describe a freshly parsed table: its shape, and its columns one by one.

    A workbook is described by its shape alone. Its cells were typed by the
    spreadsheet that wrote them rather than by the text of a source file, so
    the per-column reading below would say more than the source supports.
    """
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
            name: describe_column(rows, index)
            for index, name in enumerate(columns)
        },
    }


def describe_column(rows: list[list[Value]], index: int) -> dict:
    """Describe one column: what it holds, how varied it is and what it lacks.

    Blank cells are what a column is missing, and so is a column a ragged row
    never reaches; neither counts towards the distinct values or the type.
    """
    cells = [row[index] if index < len(row) else MISSING for row in rows]
    present = [cell for cell in cells if cell != MISSING]
    return {
        "type": column_type(present),
        "distinct_count": len(set(present)),
        "missing_count": len(cells) - len(present),
    }


def column_type(present: list[Value]) -> str:
    """Name the type of a column from the values actually in it.

    Whole numbers alone make an ``integer`` column and decimals alone a
    ``float`` one, while a column holding both is simply a ``number``.
    Anything else -- text, or a column with nothing in it -- is ``text``.
    """
    kinds = {type(value) for value in present}
    if not kinds or str in kinds:
        return TEXT
    if kinds == {int}:
        return INTEGER
    if kinds == {float}:
        return FLOAT
    return NUMBER
