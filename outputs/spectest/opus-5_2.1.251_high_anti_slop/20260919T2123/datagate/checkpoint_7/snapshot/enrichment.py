"""The `/convert` `enrich` flag and the ingestion-time metadata it records."""

from werkzeug.datastructures import MultiDict

from store import Cell, Dataset, Enrichment

ENRICH_PARAM = "enrich"
ENRICH_VALUE = "yes"

CSV_FILETYPE = "csv"
EXCEL_FILETYPE = "excel"
# Column details are reported for delimited text, where a whole column shares one inferred type.
# A workbook types every cell on its own, so only the dataset summary is reported for one.
DETAILED_FILETYPES = (CSV_FILETYPE,)

TEXT_TYPE = "text"
NUMERIC_KINDS = {int, float}
NUMERIC_TYPES = {
    frozenset({int}): "integer",
    frozenset({float}): "float",
    frozenset({int, float}): "number",
}


def parse_enrich(args: MultiDict) -> bool:
    """Read `enrich`: only the exact value `yes`, given once, asks for an enriched ingestion.

    Every other state — a different value, no value at all, the parameter repeated, the parameter
    absent — simply is not that request, so it leaves enrichment off rather than failing.
    """
    return args.getlist(ENRICH_PARAM) == [ENRICH_VALUE]


def describe(dataset: Dataset, filetype: str) -> Enrichment:
    """Summarise a freshly parsed dataset, as `enrich=yes` asks ingestion to.

    Every format gets the dataset summary; the formats with per-column types also get one entry
    per column, keyed by column name in source order.
    """
    summary = {
        "filetype": filetype,
        "row_count": len(dataset.rows),
        "column_count": len(dataset.columns),
    }
    if filetype not in DETAILED_FILETYPES:
        return {"dataset_summary": summary}
    details = {
        name: _describe_column(values) for name, values in zip(dataset.columns, zip(*dataset.rows))
    }
    return {"dataset_summary": summary, "column_details": details}


def _describe_column(values: tuple[Cell, ...]) -> dict[str, object]:
    """Describe one column: its type, how many values it holds, and how many cells are blank.

    Blanks are neither typed nor counted as a distinct value, so a column of numbers stays a
    number column when some of its rows are empty.
    """
    present = [value for value in values if not _is_missing(value)]
    return {
        "type": _column_type(present),
        "distinct_count": len(set(present)),
        "missing_count": len(values) - len(present),
    }


def _is_missing(value: Cell) -> bool:
    """A cell is missing when it carries no text: an empty or blank string, never a number."""
    return isinstance(value, str) and not value.strip()


def _column_type(present: list[Cell]) -> str:
    """Label a column from the types the parser gave its values.

    A column is `integer` or `float` when every value is one and `number` when it mixes the two.
    Anything else is `text`, an entirely blank column included — there is nothing to call it.
    """
    kinds = {type(value) for value in present}
    if kinds and kinds <= NUMERIC_KINDS:
        return NUMERIC_TYPES[frozenset(kinds)]
    return TEXT_TYPE
