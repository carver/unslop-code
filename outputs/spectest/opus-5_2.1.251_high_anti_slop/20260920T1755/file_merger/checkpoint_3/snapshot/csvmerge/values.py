"""Parsing, formatting and inference rules for the supported column types.

A *cast value* is the Python object a cell holds once parsed: ``int``,
``float``, ``bool``, ``datetime.date``, timezone-aware ``datetime.datetime``
(always UTC), ``str``, or ``None`` for a null.

Cells arrive either as text (CSV, TSV) or already typed (JSON Lines,
Parquet). Typed values are rendered to their canonical text before being
cast, so the same logical value produces the same output whichever format
carried it.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Callable, FrozenSet

# How a missing value is read while inferring: ``strict`` observes it (and
# only ``string`` fits it), ``loose`` skips it.
STRICT = "strict"
LOOSE = "loose"

# Highest priority first: the winner when several types fit every observed value.
TYPE_PRIORITY = ("timestamp", "date", "bool", "int", "float", "string")

# The types a value of a given type can also be rendered as. Inference works
# with these sets: the types that fit a value.
WIDENINGS: dict[str, FrozenSet[str]] = {
    "timestamp": frozenset({"timestamp", "string"}),
    "date": frozenset({"date", "string"}),
    "bool": frozenset({"bool", "string"}),
    "int": frozenset({"int", "float", "string"}),
    "float": frozenset({"float", "string"}),
    "string": frozenset({"string"}),
}

_INT_PATTERN = re.compile(r"[+-]?\d+")
_FLOAT_PATTERN = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
_TRUE_LITERALS = frozenset({"true", "1"})
_FALSE_LITERALS = frozenset({"false", "0"})


def parse_int(text: str) -> int:
    if not _INT_PATTERN.fullmatch(text):
        raise ValueError(f"{text!r} is not an integer")
    return int(text)


def parse_float(text: str) -> float:
    if not _FLOAT_PATTERN.fullmatch(text):
        raise ValueError(f"{text!r} is not a float")
    return float(text)


def parse_bool(text: str) -> bool:
    lowered = text.lower()
    if lowered in _TRUE_LITERALS:
        return True
    if lowered in _FALSE_LITERALS:
        return False
    raise ValueError(f"{text!r} is not a boolean")


def parse_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def parse_timestamp(text: str) -> datetime:
    """Parse an ISO-8601 datetime, normalising it to UTC.

    A date without a time component is not a timestamp, otherwise every
    ``date`` column would be promoted by the type priority. Values without a
    zone offset are taken to be UTC already.
    """
    if "T" not in text and " " not in text:
        raise ValueError(f"{text!r} has no time component")
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


_PARSERS: dict[str, Callable[[str], Any]] = {
    "int": parse_int,
    "float": parse_float,
    "bool": parse_bool,
    "date": parse_date,
    "timestamp": parse_timestamp,
    "string": str,
}


def cast(text: str, type_name: str) -> tuple[bool, Any]:
    """Return ``(True, value)`` when ``text`` parses as ``type_name``, else ``(False, None)``."""
    try:
        return True, _PARSERS[type_name](text)
    except ValueError:
        return False, None


def cast_value(value: Any, type_name: str) -> tuple[bool, Any]:
    """Cast one raw cell - text, or a value a typed source handed over."""
    return cast(value if isinstance(value, str) else format_value(value, ""), type_name)


def candidate_types(text: str) -> FrozenSet[str]:
    """Return every type name that accepts ``text``."""
    return frozenset(name for name in TYPE_PRIORITY if cast(text, name)[0])


def value_candidates(value: Any) -> FrozenSet[str]:
    """Return every type that fits ``value``, however its source spelled it.

    Text is probed against each parser; a typed value keeps its own type and
    the wider ones it can still be rendered as. A missing value - a null from
    a typed source, an empty or null-literal cell from a text one - fits only
    ``string``, which is what makes ``strict`` inference fall back to text.
    """
    if isinstance(value, str):
        return candidate_types(value)
    if value is None:
        return WIDENINGS["string"]
    return WIDENINGS[native_type(value)]


def native_type(value: Any) -> str:
    """Name the column type a non-text value belongs to."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, datetime):
        return "timestamp"
    if isinstance(value, date):
        return "date"
    return "string"


def best_type(candidates: FrozenSet[str] | None) -> str:
    """Pick the highest-priority type from ``candidates``, defaulting to ``string``."""
    for name in TYPE_PRIORITY:
        if candidates and name in candidates:
            return name
    return "string"


def format_value(value: Any, null_literal: str) -> str:
    """Render a cast value using the deterministic output dialect."""
    if value is None:
        return null_literal
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        fraction = f".{value.microsecond:06d}" if value.microsecond else ""
        return f"{value.strftime('%Y-%m-%dT%H:%M:%S')}{fraction}Z"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def comparable(value: Any) -> tuple[int, Any] | None:
    """Map a cast value onto a sortable ``(rank, primitive)`` pair, or ``None`` for a null.

    The rank keeps mixed-type columns (possible under ``--on-type-error
    keep-string``) comparable without ever comparing a number to a string.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return (2, value.timestamp())
    if isinstance(value, date):
        return (1, value.toordinal())
    if isinstance(value, (int, float)):
        return (0, value)
    return (3, value)
