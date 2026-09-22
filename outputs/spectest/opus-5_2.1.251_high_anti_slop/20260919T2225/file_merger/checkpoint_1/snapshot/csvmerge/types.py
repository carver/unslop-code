"""Column types plus the parse / format / sort-encode tables that define them.

Each supported type is described by three table entries instead of a chain of
conditionals: how to parse text into a Python value, how to render that value
back to CSV text, and how to encode it as a scalar the sorter can order.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum


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


def matching_types(text: str) -> set[ColumnType]:
    """Return every type that could be inferred from ``text`` (always includes ``string``)."""
    return {column_type for column_type, parse in INFERENCE_PARSERS.items() if _parses(parse, text)}


def _parses(parse, text: str) -> bool:
    try:
        parse(text)
    except ValueError:
        return False
    return True
