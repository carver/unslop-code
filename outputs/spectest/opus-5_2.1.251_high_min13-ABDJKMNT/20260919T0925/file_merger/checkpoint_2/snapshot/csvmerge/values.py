"""Values that arrive already typed, from JSONL and Parquet sources.

CSV and TSV hand the pipeline raw text, which `coltypes` parses. JSONL and Parquet
hand it Python objects instead, so those objects need the same two operations: which
column types could hold this value (inference), and cast it into one (output).
JSON *strings* are probed as text, exactly like a CSV cell, so a `"2024-07-01"` in
JSONL and a `2024-07-01` in CSV agree on `date` (AMBIGUITIES T27).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from .coltypes import (
    BOOL,
    DATE,
    FLOAT,
    INT,
    STRING,
    TIMESTAMP,
    CastError,
    as_utc,
    candidate_types,
    cast,
    midnight,
    render,
)

#: Bounds of the `int` range a JSONL number must fall in to stay an integer.
INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1

#: Column types each kind of typed value can be held by. Numbers deliberately omit
#: `bool`: JSON and Parquet both have a real boolean type, so `1` means one.
_CANDIDATES = {
    bool: frozenset({BOOL, STRING}),
    int: frozenset({INT, FLOAT, STRING}),
    float: frozenset({FLOAT, STRING}),
    date: frozenset({DATE, STRING}),
    datetime: frozenset({TIMESTAMP, STRING}),
}


def native(value):
    """Map a source's Python object onto the vocabulary used here."""
    return float(value) if isinstance(value, Decimal) else value


def normalize_number(value):
    """JSONL rule: an integral number within `int` range is an `int`, else a `float`."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer() and INT64_MIN <= value <= INT64_MAX:
        return int(value)
    if isinstance(value, int) and not INT64_MIN <= value <= INT64_MAX:
        return float(value)
    return value


def candidates_of(value):
    """Return every column type that could hold `value`, for schema inference."""
    if isinstance(value, str):
        return candidate_types(value)
    return _CANDIDATES.get(type(value), frozenset({STRING}))


def cast_value(column_type, value):
    """Cast `value` into `column_type`, raising `CastError` on failure.

    Text goes through the string parsers; typed values convert across families the
    same way those parsers do — `0`/`1` are booleans, a fractional number is not an
    `int`, and a date widens to midnight UTC but a timestamp never narrows to a date
    (AMBIGUITIES T28).
    """
    if isinstance(value, str):
        return cast(column_type, value)
    return _TYPED_CASTS[column_type](value)


def _to_string(value):
    return render(value, "")


def _to_int(value):
    if isinstance(value, (bool, int)):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise CastError(f"not an int: {value!r}")


def _to_float(value):
    if isinstance(value, (bool, int, float)):
        return float(value)
    raise CastError(f"not a float: {value!r}")


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    raise CastError(f"not a bool: {value!r}")


def _to_date(value):
    if type(value) is date:
        return value
    raise CastError(f"not a date: {value!r}")


def _to_timestamp(value):
    if isinstance(value, datetime):
        return as_utc(value)
    if type(value) is date:
        return midnight(value)
    raise CastError(f"not a timestamp: {value!r}")


_TYPED_CASTS = {
    STRING: _to_string,
    INT: _to_int,
    FLOAT: _to_float,
    BOOL: _to_bool,
    DATE: _to_date,
    TIMESTAMP: _to_timestamp,
}
