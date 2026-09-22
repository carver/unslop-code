"""Parsing and application of the ``/datasets`` control parameters.

The control parameters (``_size``, ``_offset``, ``_shape``, ``_sort``, ``_sort_desc``,
``_rowid`` and ``_total``) decide how many rows a dataset query returns, in what order,
and in what shape. None of them may be repeated in a query string.

A query runs its filters first, then sorts, then paginates; see ``filtering``.
"""

from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from .errors import DataGateError
from .filtering import Filter, matching_rows
from .store import Dataset
from .timing import Deadline
from .values import Value, sort_key

DEFAULT_SIZE = 100
QUERY_TIMEOUT_SECONDS = 5.0
SHAPES = ("lists", "objects")

Row = list[Value] | dict[str, Value]


@dataclass(frozen=True)
class Selection:
    """The rows one query returns, and how many rows it matched before paginating."""

    rows: list[Row]
    total: int


@dataclass(frozen=True)
class Controls:
    """The requested pagination, ordering and response shape for one query."""

    size: int
    offset: int
    shape: str
    sort_column: str | None
    descending: bool
    with_rowid: bool
    with_total: bool


def read_controls(args: MultiDict[str, str], columns: list[str]) -> Controls:
    """Read the control parameters from a query string.

    The sort parameters are checked against ``columns``, the dataset's column names.
    Every problem raises a 400 error naming the offending parameter.
    """
    sort_column, descending = _sort_order(args, columns)
    return Controls(
        size=_whole_number(args, "_size", default=DEFAULT_SIZE, minimum=1),
        offset=_whole_number(args, "_offset", default=0, minimum=0),
        shape=_choice(args, "_shape", SHAPES, default="lists"),
        sort_column=sort_column,
        descending=descending,
        with_rowid=_choice(args, "_rowid", ("hide",), default=None) is None,
        with_total=_choice(args, "_total", ("hide",), default=None) is None,
    )


def select_rows(
    dataset: Dataset, controls: Controls, filters: list[Filter]
) -> Selection:
    """Return the dataset's matching rows sorted, then paginated, then shaped.

    Rows keep the 1-based position they had in the source file, which ``objects`` shape
    reports as ``rowid``. The reported total counts the matching rows before pagination.
    A query that outlives its time budget fails with a 400 error.
    """
    deadline = Deadline(QUERY_TIMEOUT_SECONDS)
    numbered = matching_rows(dataset, filters, deadline)
    if controls.sort_column is not None:
        position = dataset.columns.index(controls.sort_column)
        numbered.sort(
            key=lambda pair: sort_key(pair[1][position]), reverse=controls.descending
        )
        deadline.check()

    page = numbered[controls.offset : controls.offset + controls.size]
    if controls.shape == "lists":
        rows: list[Row] = [row for _, row in page]
    else:
        rows = [
            _as_object(rowid, row, dataset.columns, controls.with_rowid)
            for rowid, row in page
        ]
    return Selection(rows=rows, total=len(numbered))


def _as_object(
    rowid: int, row: list[Value], columns: list[str], with_rowid: bool
) -> dict[str, Value]:
    """Pair a row's cells with their column names, leading with ``rowid`` when shown."""
    fields: dict[str, Value] = {"rowid": rowid} if with_rowid else {}
    fields.update(zip(columns, row))
    return fields


def _single(args: MultiDict[str, str], name: str) -> str | None:
    """Return the one value given for ``name``, rejecting a repeated parameter."""
    values = args.getlist(name)
    if len(values) > 1:
        raise DataGateError(f"query parameter {name!r} must not be repeated", 400)
    return values[0] if values else None


def _whole_number(
    args: MultiDict[str, str], name: str, *, default: int, minimum: int
) -> int:
    """Read ``name`` as an integer of at least ``minimum``, defaulting when absent."""
    raw = _single(args, name)
    if raw is None:
        return default
    if not raw.isdigit() or int(raw) < minimum:
        wanted = "a positive integer" if minimum else "a non-negative integer"
        raise DataGateError(f"query parameter {name!r} must be {wanted}", 400)
    return int(raw)


def _choice(
    args: MultiDict[str, str], name: str, allowed: tuple[str, ...], default: str | None
) -> str | None:
    """Read ``name`` as one of ``allowed``, defaulting when absent."""
    raw = _single(args, name)
    if raw is None:
        return default
    if raw not in allowed:
        listed = " or ".join(repr(value) for value in allowed)
        raise DataGateError(f"query parameter {name!r} must be {listed}", 400)
    return raw


def _sort_order(
    args: MultiDict[str, str], columns: list[str]
) -> tuple[str | None, bool]:
    """Return the column to sort on and whether to reverse it.

    ``_sort_desc`` takes precedence when both sort parameters are present.
    """
    ascending = _single(args, "_sort")
    descending = _single(args, "_sort_desc")
    chosen = ascending if descending is None else descending
    if chosen is None:
        return None, False
    if chosen not in columns:
        raise DataGateError(f"cannot sort on unknown column {chosen!r}", 400)
    return chosen, descending is not None
