"""Column types plus the parse / format / sort-encode tables that define them.

Each supported type is described by three table entries instead of a chain of
conditionals: how to parse text into a Python value, how to render that value
back to CSV text, and how to encode it as a scalar the sorter can order.

Values from JSON Lines and Parquet arrive already typed. They are rendered with
:func:`as_text` and then run through the same parsers as text, so a source's
format never changes what a column ends up holding.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any


class ColumnType(str, Enum):
    """Types a column may take, declared in descending inference priority."""

    TIMESTAMP = "timestamp"
    DATE = "date"
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    STRING = "string"


#: Inference priority: the first entry that accepts every observed value wins.
TYPE_PRIORITY = tuple(ColumnType)

_BOOL_LITERALS = {"true": True, "false": False, "1": True, "0": False}

#: Index of the ``T``/space separator that distinguishes a timestamp from a date.
_TIME_SEPARATOR_POSITION = 10


def parse_bool(text: str) -> bool:
    """Parse ``true``/``false`` (any case) as well as ``1``/``0``."""
    value = _BOOL_LITERALS.get(text.strip().lower())
    if value is None:
        raise ValueError(f"not a boolean: {text!r}")
    return value


def _parse_bool_literal(text: str) -> bool:
    """Inference variant of :func:`parse_bool` that rejects ``1``/``0``.

    Numbers stay numbers when a type is inferred; the ``1``/``0`` spelling is
    only honoured when a column is explicitly declared as a bool.
    """
    if text.strip().lower() not in ("true", "false"):
        raise ValueError(f"not a boolean literal: {text!r}")
    return parse_bool(text)


def parse_date(text: str) -> date:
    """Parse an ISO-8601 calendar date (``YYYY-MM-DD``)."""
    return datetime.strptime(text.strip(), "%Y-%m-%d").date()


def parse_timestamp(text: str) -> datetime:
    """Parse an ISO-8601 timestamp: a missing zone is UTC, a bare date is UTC midnight."""
    parsed = datetime.fromisoformat(text.strip())
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_dated_timestamp(text: str) -> datetime:
    """Inference variant of :func:`parse_timestamp` that rejects a bare date.

    Without this, every date would also qualify as a timestamp and the higher
    priority of ``timestamp`` would stop ``date`` from ever being inferred.
    """
    if text.strip()[_TIME_SEPARATOR_POSITION : _TIME_SEPARATOR_POSITION + 1] not in ("T", "t", " "):
        raise ValueError(f"not a timestamp: {text!r}")
    return parse_timestamp(text)


def format_timestamp(value: datetime) -> str:
    """Render a timestamp in UTC with the ``Z`` suffix."""
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


PARSERS = {
    ColumnType.TIMESTAMP: parse_timestamp,
    ColumnType.DATE: parse_date,
    ColumnType.BOOL: parse_bool,
    ColumnType.INT: int,
    ColumnType.FLOAT: float,
    ColumnType.STRING: str,
}

FORMATTERS = {
    ColumnType.TIMESTAMP: format_timestamp,
    ColumnType.DATE: date.isoformat,
    ColumnType.BOOL: lambda value: "true" if value else "false",
    ColumnType.INT: str,
    ColumnType.FLOAT: repr,
    ColumnType.STRING: str,
}

#: Maps a parsed value to a scalar that orders identically and survives JSON
#: round-tripping through the sorter's spill files.
SORT_ENCODERS = {
    ColumnType.TIMESTAMP: datetime.timestamp,
    ColumnType.DATE: date.toordinal,
    ColumnType.BOOL: int,
    ColumnType.INT: int,
    ColumnType.FLOAT: float,
    ColumnType.STRING: str,
}


#: Parsers used while inferring. They are deliberately narrower than
#: :data:`PARSERS`: a higher-priority type must not swallow values that a
#: lower-priority one describes better (a bare date, or a numeric ``1``/``0``).
INFERENCE_PARSERS = {
    **PARSERS,
    ColumnType.TIMESTAMP: _parse_dated_timestamp,
    ColumnType.BOOL: _parse_bool_literal,
}


#: How a value that arrived already typed is rendered before parsing. Exact
#: types are matched, so a ``datetime`` never falls through to ``date``.
_TEXT_RENDERERS = {
    bool: FORMATTERS[ColumnType.BOOL],
    datetime: FORMATTERS[ColumnType.TIMESTAMP],
    date: FORMATTERS[ColumnType.DATE],
}

#: Types that a value observed in a typed source could be inferred as.
_TYPED_CANDIDATES = {
    bool: {ColumnType.BOOL, ColumnType.STRING},
    int: {ColumnType.INT, ColumnType.FLOAT, ColumnType.STRING},
    float: {ColumnType.FLOAT, ColumnType.STRING},
    datetime: {ColumnType.TIMESTAMP, ColumnType.STRING},
    date: {ColumnType.DATE, ColumnType.STRING},
}


def as_text(value: Any) -> str:
    """Render any source value the way this tool writes that type to CSV."""
    return _TEXT_RENDERERS.get(type(value), str)(value)


def cast_value(value: Any, column_type: ColumnType):
    """Cast one source value — text or already typed — into ``column_type``.

    Whole floats are the single shortcut: a Parquet or JSON ``3.0`` satisfies an
    ``int`` column, while ``3.5`` still fails as it would coming from text.
    """
    if column_type is ColumnType.INT and isinstance(value, float) and value.is_integer():
        return int(value)
    return PARSERS[column_type](as_text(value))


def candidate_types(value: Any) -> set[ColumnType]:
    """Return every type that could be inferred from one observed value.

    Text is judged by what parses; typed values are judged by their own type, so
    a JSON string of digits stays inferable as an ``int`` while a JSON number
    that happens to read like a date does not become one.
    """
    if isinstance(value, str):
        return matching_types(value)
    return _TYPED_CANDIDATES.get(type(value), {ColumnType.STRING})


def matching_types(text: str) -> set[ColumnType]:
    """Return every type that could be inferred from ``text`` (always includes ``string``)."""
    return {column_type for column_type, parse in INFERENCE_PARSERS.items() if _parses(parse, text)}


def _parses(parse, text: str) -> bool:
    try:
        parse(text)
    except ValueError:
        return False
    return True
