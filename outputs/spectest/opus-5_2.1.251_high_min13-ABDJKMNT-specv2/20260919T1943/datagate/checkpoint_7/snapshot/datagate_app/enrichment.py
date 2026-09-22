"""Optional ingestion enrichment: the `enrich=yes` flag and the metadata it attaches.

Enrichment is a property of an *ingested* dataset rather than of a query: the
metadata is computed once from the bytes that were parsed, stored alongside the
table, and then repeated by every query of that dataset (T78). So a filtered or
paginated request reports the same counts as an unfiltered one.
"""

from typing import Any

from werkzeug.datastructures import MultiDict

from .formats import SourceFormat
from .parsing import Dataset

ENRICH = "enrich"
ENABLED_VALUE = "yes"

# Which numeric label a column earns, by the set of Python types its cells hold.
# A set that is not here -- one holding `str`, or an empty one -- is a text column (T75).
_NUMERIC_LABELS = {
    frozenset({int}): "integer",
    frozenset({float}): "float",
    frozenset({int, float}): "number",
}
_TEXT_LABEL = "text"


def enrich_requested(args: MultiDict) -> bool:
    """Whether a request asked for enrichment.

    Only one exact `enrich=yes` turns it on; every other state -- another value,
    a valueless flag, or the parameter more than once -- leaves enrichment off
    without being an error (T72).
    """
    return args.getlist(ENRICH) == [ENABLED_VALUE]


def describe(dataset: Dataset, source_format: SourceFormat) -> dict[str, Any]:
    """Build the metadata fields an enriched dataset reports.

    A workbook is summarised but not profiled per column, so a spreadsheet
    dataset carries `dataset_summary` alone (T74).
    """
    is_csv = source_format is SourceFormat.CSV
    summary = {
        "filetype": "csv" if is_csv else "excel",
        "row_count": len(dataset.rows),
        "column_count": len(dataset.columns),
    }
    if not is_csv:
        return {"dataset_summary": summary}
    return {"dataset_summary": summary, "column_details": _column_details(dataset)}


def _column_details(dataset: Dataset) -> dict[str, dict[str, Any]]:
    """Profile every column of `dataset`, keyed by its header name."""
    return {
        name: _column_detail([row.values[index] for row in dataset.rows])
        for index, name in enumerate(dataset.columns)
    }


def _column_detail(cells: list[Any]) -> dict[str, Any]:
    """Summarise one column: its type label plus how many values it has and lacks.

    Missing cells are set aside first, so they are counted once as absences
    rather than also as a distinct value or as evidence of a text column (T76, T77).
    """
    present = [cell for cell in cells if not _is_missing(cell)]
    return {
        "type": _NUMERIC_LABELS.get(frozenset(type(cell) for cell in present), _TEXT_LABEL),
        "distinct_count": len(set(present)),
        "missing_count": len(cells) - len(present),
    }


def _is_missing(cell: Any) -> bool:
    """An empty or blank cell -- including the padding of a row shorter than the header."""
    return isinstance(cell, str) and not cell.strip()
