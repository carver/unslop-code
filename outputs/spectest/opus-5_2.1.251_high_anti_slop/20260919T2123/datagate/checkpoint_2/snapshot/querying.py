"""Control parameters for dataset reads: pagination, sorting and response shape."""

from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from errors import DatagateError
from store import Dataset, Row

DEFAULT_SIZE = 100
DEFAULT_SHAPE = "lists"
SHAPES = ("lists", "objects")
HIDE = "hide"
CONTROL_PARAMS = ("_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total")


@dataclass(frozen=True)
class DatasetQuery:
    """The control parameters of one dataset read, already validated against the dataset."""

    size: int
    offset: int
    shape: str
    sort: str | None
    descending: bool
    show_rowid: bool
    show_total: bool


def parse_query(args: MultiDict, columns: list[str]) -> DatasetQuery:
    """Read the control parameters from a query string, rejecting anything unusable with 400."""
    _reject_repeats(args)
    sort, descending = _parse_sort(args, columns)
    return DatasetQuery(
        size=_parse_count(args, "_size", default=DEFAULT_SIZE, minimum=1),
        offset=_parse_count(args, "_offset", default=0, minimum=0),
        shape=_parse_shape(args),
        sort=sort,
        descending=descending,
        show_rowid=_parse_toggle(args, "_rowid"),
        show_total=_parse_toggle(args, "_total"),
    )


def select_rows(dataset: Dataset, query: DatasetQuery) -> list[Row] | list[dict]:
    """Sort, then paginate, then shape the dataset's rows.

    Rows are numbered before sorting so that `rowid` keeps pointing at the source file row
    however the page is ordered or sliced.
    """
    numbered = list(enumerate(dataset.rows, start=1))
    if query.sort is not None:
        position = dataset.columns.index(query.sort)
        numbered.sort(key=lambda pair: _sort_key(pair[1][position]), reverse=query.descending)

    page = numbered[query.offset : query.offset + query.size]
    if query.shape == "objects":
        return _as_objects(dataset.columns, page, query.show_rowid)
    return [row for _, row in page]


def _reject_repeats(args: MultiDict) -> None:
    """A control parameter given twice is ambiguous, so it is an error rather than a guess."""
    repeated = [name for name in CONTROL_PARAMS if len(args.getlist(name)) > 1]
    if repeated:
        raise DatagateError(400, f"Repeated query parameter(s): {', '.join(repeated)}")


def _parse_count(args: MultiDict, name: str, default: int, minimum: int) -> int:
    """Read a whole-number parameter; `isdecimal` is what rules out signs, decimals and text."""
    raw = args.get(name)
    if raw is None:
        return default
    if not raw.isdecimal() or int(raw) < minimum:
        raise DatagateError(
            400, f"Query parameter {name!r} must be an integer of at least {minimum}, got {raw!r}"
        )
    return int(raw)


def _parse_shape(args: MultiDict) -> str:
    shape = args.get("_shape", DEFAULT_SHAPE)
    if shape not in SHAPES:
        raise DatagateError(
            400, f"Query parameter '_shape' must be one of {', '.join(SHAPES)}, got {shape!r}"
        )
    return shape


def _parse_toggle(args: MultiDict, name: str) -> bool:
    """Visibility toggles only ever hide: absent means visible, `hide` means hidden."""
    raw = args.get(name)
    if raw is None:
        return True
    if raw != HIDE:
        raise DatagateError(400, f"Query parameter {name!r} only accepts {HIDE!r}, got {raw!r}")
    return False


def _parse_sort(args: MultiDict, columns: list[str]) -> tuple[str | None, bool]:
    """Resolve the sort column and direction. `_sort_desc` wins when both are present."""
    for name, descending in (("_sort_desc", True), ("_sort", False)):
        if name not in args:
            continue
        column = args[name]
        if column not in columns:
            raise DatagateError(
                400, f"Query parameter {name!r} must name a dataset column, got {column!r}"
            )
        return column, descending
    return None, False


def _sort_key(value: str | int | float) -> tuple:
    """Order numbers ahead of text so a column mixing the two (`7` and `n/a`) stays sortable."""
    if isinstance(value, (int, float)):
        return (0, value, "")
    return (1, 0, value)


def _as_objects(columns: list[str], page: list[tuple[int, Row]], show_rowid: bool) -> list[dict]:
    """Objects shape: one dict per row, led by the source row number unless it is hidden."""
    if show_rowid:
        return [{"rowid": rowid, **dict(zip(columns, row))} for rowid, row in page]
    return [dict(zip(columns, row)) for _, row in page]
