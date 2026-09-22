"""Column types: parsing input text, inferring candidates, rendering output text.

The type vocabulary and the priority order come straight from the spec:
``timestamp`` > ``date`` > ``bool`` > ``int`` > ``float`` > ``string``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

STRING = "string"
INT = "int"
FLOAT = "float"
BOOL = "bool"
DATE = "date"
TIMESTAMP = "timestamp"

#: Highest priority first; `resolve_priority` picks the first entry it can.
TYPE_PRIORITY = (TIMESTAMP, DATE, BOOL, INT, FLOAT, STRING)
VALID_TYPES = frozenset(TYPE_PRIORITY)

_TRUE_TEXT = frozenset({"true", "1"})
_FALSE_TEXT = frozenset({"false", "0"})
_DATE_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
#: A timestamp is only *inferred* when the text carries a time component, which is
#: what keeps `date` reachable under the priority order (see AMBIGUITIES T4).
_DATETIME_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


class CastError(ValueError):
    """Raised when a cell cannot be represented as the requested column type."""


@dataclass(frozen=True)
class KeptText:
    """Original cell text preserved by ``--on-type-error keep-string``."""

    text: str


def _parse_int(text):
    return int(text)


def _parse_float(text):
    return float(text)


def _parse_bool(text):
    lowered = text.lower()
    if lowered in _TRUE_TEXT:
        return True
    if lowered in _FALSE_TEXT:
        return False
    raise CastError(f"not a bool: {text!r}")


def _parse_date(text):
    if not _DATE_TEXT.match(text):
        raise CastError(f"not an ISO-8601 date: {text!r}")
    return date.fromisoformat(text)


def as_utc(moment):
    """Normalize a datetime to UTC, reading a naive one as already being UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def midnight(day):
    """Widen a date into the UTC timestamp at the start of that day."""
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _parse_datetime(text):
    """Parse ISO-8601 text that carries a time component, normalized to UTC."""
    if not _DATETIME_TEXT.match(text):
        raise CastError(f"not an ISO-8601 timestamp: {text!r}")
    return as_utc(datetime.fromisoformat(text))


def _cast_timestamp(text):
    """Cast into a timestamp, widening a date-only source to midnight UTC."""
    try:
        return _parse_datetime(text)
    except CastError:
        return midnight(_parse_date(text))


#: Parsers used when casting a cell into a declared column type.
_CASTS = {
    STRING: str,
    INT: _parse_int,
    FLOAT: _parse_float,
    BOOL: _parse_bool,
    DATE: _parse_date,
    TIMESTAMP: _cast_timestamp,
}

#: Parsers used when inferring a type; stricter than `_CASTS` for timestamps.
_PROBES = dict(_CASTS, **{TIMESTAMP: _parse_datetime})


def cast(column_type, text):
    """Cast `text` into `column_type`, raising `CastError` on failure."""
    try:
        return _CASTS[column_type](text)
    except CastError:
        raise
    except ValueError as error:
        raise CastError(f"not a {column_type}: {text!r}") from error


def candidate_types(text):
    """Return every type `text` could be, for schema inference."""
    candidates = set()
    for column_type, probe in _PROBES.items():
        try:
            probe(text)
        except ValueError:
            continue
        candidates.add(column_type)
    return candidates


def resolve_priority(candidates):
    """Pick the highest-priority type among `candidates`, defaulting to `string`."""
    return next((name for name in TYPE_PRIORITY if name in candidates), STRING)


def render(value, null_literal):
    """Render a cast value as output text (see AMBIGUITIES T1 and T9).

    A nested value renders as the canonical JSON that is its whole CSV cell.
    """
    if value is None:
        return null_literal
    if isinstance(value, KeptText):
        return value.text
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat() + "Z"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    return str(value)


def canonical_json(value):
    """Serialize a nested value as minified UTF-8 JSON (see AMBIGUITIES T48).

    Ordering is already baked into the value: struct fields were built in their
    declared order and map keys were sorted while casting, and `dict` preserves both.
    """
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=_as_json_text)


def _as_json_text(value):
    """Render the values JSON has no type for — dates, timestamps, kept text."""
    return render(value, "")
