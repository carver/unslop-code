"""Optional ingestion metadata, requested with ``enrich=yes`` on ``/convert``.

Enrichment is computed once, while a source is being ingested, and stored alongside the
dataset so that every query of it reports the same metadata. Datasets converted without
it carry none, and report none.
"""

from collections.abc import Sequence

from werkzeug.datastructures import MultiDict

from .tables import EXCEL, Table
from .values import Value

Metadata = dict[str, dict]


def wants_enrichment(args: MultiDict[str, str]) -> bool:
    """Return whether a ``/convert`` request asked for ingestion metadata.

    Only a single, exact ``enrich=yes`` turns enrichment on; any other value, spelling
    or repetition leaves it off rather than failing the request.
    """
    return args.getlist("enrich") == ["yes"]


def describe(table: Table) -> Metadata:
    """Return the ingestion metadata for a freshly parsed table.

    A spreadsheet is summarised only: its cells keep the types the workbook itself
    recorded, so per-column inference would describe the workbook's formatting rather
    than the data, and ``column_details`` is left off.
    """
    summary = {
        "filetype": table.filetype,
        "row_count": len(table.rows),
        "column_count": len(table.columns),
    }
    if table.filetype == EXCEL:
        return {"dataset_summary": summary}

    details = {
        name: _describe_column(cells)
        for name, cells in zip(table.columns, zip(*table.rows))
    }
    return {"dataset_summary": summary, "column_details": details}


def _describe_column(cells: Sequence[Value]) -> dict[str, Value]:
    """Return one column's inferred type and its distinct and missing cell counts.

    A cell is missing when it holds no text -- an empty cell, or one a shorter source
    row was padded out with -- and missing cells count towards neither the column's
    type nor its distinct values.
    """
    present = [cell for cell in cells if not _is_missing(cell)]
    return {
        "type": _column_type(present),
        "distinct_count": len(set(present)),
        "missing_count": len(cells) - len(present),
    }


def _is_missing(cell: Value) -> bool:
    """Return whether a cell holds nothing, blank text included."""
    return isinstance(cell, str) and not cell.strip()


def _column_type(present: list[Value]) -> str:
    """Label a column by the types its cells were parsed into.

    Numeric columns are reported as precisely as their cells allow: ``integer`` or
    ``float`` when every cell is one of those, and ``number`` when they are mixed. A
    column holding any text at all -- including one that is entirely missing -- is
    ``text``, since that is how its cells are stored and compared.
    """
    kinds = {type(cell) for cell in present}
    if not kinds or str in kinds:
        return "text"
    if kinds == {int}:
        return "integer"
    if kinds == {float}:
        return "float"
    return "number"
