"""Column types: recognition, casting and deterministic output formatting.

Cells arrive either as text (CSV, TSV) or already typed (JSON Lines, Parquet).
``cast_value`` accepts both: text is parsed, typed values are converted.
``candidates`` reports every type a cell could take, which is what schema
inference works from, and ``format_value`` renders a cast value for output.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from typing import Any, Callable, Iterable


class ColumnType(str, Enum):
    """The types a resolved schema column may have."""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    DATE = "date"
    TIMESTAMP = "timestamp"


#: Order used to pick a column type from the set of types every one of its
#: values matches: the first match wins, so the most specific type is chosen.
#: ``date`` precedes ``timestamp`` because a column of plain ``YYYY-MM-DD``
#: values stays a date; as soon as one value carries a time component only
#: ``timestamp`` remains a candidate and the column is promoted to it, which is
#: the ``timestamp > date`` priority.
INFERENCE_ORDER = (
    ColumnType.DATE,
    ColumnType.TIMESTAMP,
    ColumnType.BOOL,
    ColumnType.INT,
    ColumnType.FLOAT,
    ColumnType.STRING,
)

#: Types a column can take when a self-describing source (Parquet) already
#: declares it, i.e. the declared type plus everything it widens into.
DECLARED_CANDIDATES = {
    ColumnType.STRING: frozenset({ColumnType.STRING}),
    ColumnType.INT: frozenset({ColumnType.INT, ColumnType.FLOAT, ColumnType.STRING}),
    ColumnType.FLOAT: frozenset({ColumnType.FLOAT, ColumnType.STRING}),
    ColumnType.BOOL: frozenset({ColumnType.BOOL, ColumnType.STRING}),
    ColumnType.DATE: frozenset({ColumnType.DATE, ColumnType.TIMESTAMP, ColumnType.STRING}),
    ColumnType.TIMESTAMP: frozenset({ColumnType.TIMESTAMP, ColumnType.STRING}),
}

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?\Z",
    re.IGNORECASE,
)
_TRUE_LITERALS = frozenset({"true", "1"})
_FALSE_LITERALS = frozenset({"false", "0"})

#: Range a typed integer must fall in to stay an ``int``; wider numbers are
#: only representable as ``float``.
_INT64 = range(-(2**63), 2**63)


class CastError(ValueError):
    """Raised when a cell cannot be represented as its column's type."""


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{value!r} is not a finite number")
    return value


def _as_utc(moment: datetime) -> datetime:
    """Read a naive timestamp as UTC and normalise an aware one to UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _parse_bool(text: str) -> bool:
    lowered = text.lower()
    if lowered in _TRUE_LITERALS:
        return True
    if lowered in _FALSE_LITERALS:
        return False
    raise ValueError(f"{text!r} is not a boolean")


def _parse_date(text: str) -> date:
    if not _DATE_PATTERN.match(text):
        raise ValueError(f"{text!r} is not an ISO-8601 date")
    return date.fromisoformat(text)


def _parse_timestamp(text: str) -> datetime:
    """Parse an ISO-8601 timestamp (or plain date) and normalise it to UTC."""
    if not _TIMESTAMP_PATTERN.match(text) and not _DATE_PATTERN.match(text):
        raise ValueError(f"{text!r} is not an ISO-8601 timestamp")
    normalised = f"{text[:-1]}+00:00" if text[-1] in "Zz" else text
    return _as_utc(datetime.fromisoformat(normalised))


_PARSERS: dict[ColumnType, Callable[[str], Any]] = {
    ColumnType.STRING: str,
    ColumnType.INT: int,
    ColumnType.FLOAT: lambda text: _finite(float(text)),
    ColumnType.BOOL: _parse_bool,
    ColumnType.DATE: _parse_date,
    ColumnType.TIMESTAMP: _parse_timestamp,
}


def format_value(value: Any) -> str:
    """Render a cast value using the output dialect's textual conventions."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _to_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{value!r} is not a number")
    if value != int(value):
        raise ValueError(f"{value!r} is not a whole number")
    if int(value) not in _INT64:
        raise ValueError(f"{value!r} does not fit in a 64-bit integer")
    return int(value)


def _to_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{value!r} is not a number")
    return _finite(float(value))


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise TypeError(f"{value!r} is not a boolean")


def _to_date(value: Any) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{value!r} is not a date")
    return value


def _to_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    raise TypeError(f"{value!r} is not a timestamp")


_CONVERTERS: dict[ColumnType, Callable[[Any], Any]] = {
    ColumnType.STRING: format_value,
    ColumnType.INT: _to_int,
    ColumnType.FLOAT: _to_float,
    ColumnType.BOOL: _to_bool,
    ColumnType.DATE: _to_date,
    ColumnType.TIMESTAMP: _to_timestamp,
}


def cast(text: str, column_type: ColumnType) -> Any:
    """Cast raw cell text into ``column_type``, raising ``CastError`` on failure."""
    try:
        return _PARSERS[column_type](text)
    except ValueError as error:
        raise CastError(str(error)) from error


def cast_value(value: Any, column_type: ColumnType) -> Any:
    """Cast any cell into ``column_type``.

    Text from CSV and TSV is parsed with the rules above; values that arrive
    typed from JSON Lines or Parquet are converted directly, so a JSON number
    only becomes an ``int`` column when it is whole and fits in 64 bits.  A
    nested value never fits a primitive column, not even ``string``.
    """
    if isinstance(value, str):
        return cast(value, column_type)
    if isinstance(value, (dict, list)):
        raise CastError(f"{value!r} is a nested value, not a {column_type.value}")
    try:
        return _CONVERTERS[column_type](value)
    except (TypeError, ValueError) as error:
        raise CastError(str(error)) from error


@lru_cache(maxsize=8192)
def candidate_types(text: str) -> frozenset[ColumnType]:
    """Every type ``text`` can be cast to; ``string`` is always among them."""
    return _castable(text)


def candidates(value: Any) -> frozenset[ColumnType]:
    """Every type a cell can be cast to, whether it holds text or a value."""
    if isinstance(value, str):
        return candidate_types(value)
    return _castable(value)


def _castable(value: Any) -> frozenset[ColumnType]:
    matches = {ColumnType.STRING}
    for column_type in INFERENCE_ORDER:
        try:
            cast_value(value, column_type)
        except CastError:
            continue
        matches.add(column_type)
    return frozenset(matches)


def narrowest(types: Iterable[ColumnType]) -> ColumnType:
    """Pick the most specific type of a candidate set, per ``INFERENCE_ORDER``."""
    remaining = set(types)
    return next(column_type for column_type in INFERENCE_ORDER if column_type in remaining)

