"""The primitive types a column can hold: parsing, rendering and ordering.

Every type knows four things:

``parse``
    Turn a CSV cell into a Python value, raising :class:`ValueError` when the
    text does not belong to the type.
``render``
    Turn that value back into the canonical text written to the output CSV.
``sort_value``
    Turn that value into something JSON serialisable whose natural ordering
    matches the type's ordering, so that keys survive a trip through a
    temporary spill file.
``to_json``
    Turn that value into its form inside a nested column's JSON: numbers,
    booleans and strings stay themselves, dates and instants become text.

:mod:`nested_types` builds the struct, array and map types on top of these.

JSON Lines and Parquet hand over values that are already typed.  They reach
the parsers through :func:`canonical_text`, and they are typed for inference by
:func:`value_candidates` rather than by parsing their text, so that the JSON
number ``1`` stays an integer instead of becoming the boolean ``true``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable, Iterable

from casting import CastContext, compact_json
from records import FieldValue

# Widest integer a Parquet or JSON Lines number can hold as an int.
INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1

# Highest priority first: when a column's values parse as several types, the
# first entry that fits them all wins.
TYPE_PRIORITY = ("timestamp", "date", "bool", "int", "float", "string")

_INT_RE = re.compile(r"[+-]?[0-9]+\Z")
_FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_TIMESTAMP_RE = re.compile(
    r"(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})[T ]"
    r"(?P<clock>[0-9]{2}:[0-9]{2}(?::[0-9]{2})?)"
    r"(?:\.(?P<fraction>[0-9]+))?"
    r"(?P<zone>[Zz]|[+-][0-9]{2}:?[0-9]{2})?\Z"
)
_TRUE_LITERALS = frozenset({"true", "1"})
_FALSE_LITERALS = frozenset({"false", "0"})

# Fractional seconds are padded to this width in sort keys so that timestamps
# compare correctly as plain strings.
_SORT_FRACTION_WIDTH = 9


@dataclass(frozen=True)
class Timestamp:
    """An instant normalised to UTC, remembering how its fraction was written."""

    moment: datetime
    fraction: str


def _parse_int(text: str) -> int:
    stripped = text.strip()
    if not _INT_RE.match(stripped):
        raise ValueError(f"not an integer: {text!r}")
    return int(stripped)


def _parse_float(text: str) -> float:
    stripped = text.strip()
    if not _FLOAT_RE.match(stripped):
        raise ValueError(f"not a float: {text!r}")
    return float(stripped)


def _parse_bool(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered in _TRUE_LITERALS:
        return True
    if lowered in _FALSE_LITERALS:
        return False
    raise ValueError(f"not a boolean: {text!r}")


def _parse_date(text: str) -> date:
    stripped = text.strip()
    if not _DATE_RE.match(stripped):
        raise ValueError(f"not an ISO-8601 date: {text!r}")
    return date.fromisoformat(stripped)


def _parse_timestamp(text: str) -> Timestamp:
    match = _TIMESTAMP_RE.match(text.strip())
    if match is None:
        raise ValueError(f"not an ISO-8601 timestamp: {text!r}")
    clock = match["clock"] if len(match["clock"]) == 8 else f"{match['clock']}:00"
    # A missing zone is read as UTC, as the spec requires.
    zone = (match["zone"] or "Z").upper()
    moment = datetime.fromisoformat(f"{match['day']}T{clock}{zone}")
    return Timestamp(moment.astimezone(timezone.utc), match["fraction"] or "")


def _identity(value: object) -> object:
    """Values that are already comparable and JSON friendly sort as themselves."""
    return value


def _render_bool(value: bool) -> str:
    return "true" if value else "false"


def _render_timestamp(value: Timestamp) -> str:
    fraction = f".{value.fraction}" if value.fraction else ""
    return f"{value.moment:%Y-%m-%dT%H:%M:%S}{fraction}Z"


def _timestamp_sort_value(value: Timestamp) -> str:
    return f"{value.moment:%Y-%m-%dT%H:%M:%S}.{value.fraction:0<{_SORT_FRACTION_WIDTH}}"


@dataclass(frozen=True)
class ColumnType:
    """One supported primitive type and the operations defined on it."""

    name: str
    parse: Callable[[str], object]
    render: Callable[[object], str]
    sort_value: Callable[[object], object]
    to_json: Callable[[object], object]

    def cast(self, value: FieldValue, context: CastContext) -> object:
        """Parse ``value`` into this type, or recover the way the flags ask.

        An object or an array never belongs to a primitive column, so it is a
        failed cast whose text is its JSON, like any other bad value.
        """
        if value is None:
            return None
        text = canonical_text(value)
        if isinstance(value, (dict, list)):
            return context.recover(text, self.name)
        try:
            return self.parse(text)
        except ValueError:
            return context.recover(text, self.name)


TYPES: dict[str, ColumnType] = {
    column_type.name: column_type
    for column_type in (
        ColumnType("string", str, str, _identity, _identity),
        ColumnType("int", _parse_int, str, _identity, _identity),
        ColumnType("float", _parse_float, str, _identity, _identity),
        ColumnType("bool", _parse_bool, _render_bool, _identity, _identity),
        ColumnType("date", _parse_date, date.isoformat, date.isoformat, date.isoformat),
        ColumnType(
            "timestamp", _parse_timestamp, _render_timestamp, _timestamp_sort_value,
            _render_timestamp,
        ),
    )
}


def matching_types(text: str, among: Iterable[str]) -> set[str]:
    """Return the names in ``among`` whose type can parse ``text``.

    Inference narrows a column's candidates value by value, so it only ever
    asks about the types that are still in the running.
    """
    matches = set()
    for name in among:
        try:
            TYPES[name].parse(text)
        except ValueError:
            continue
        matches.add(name)
    return matches


def best_type(candidates: set[str]) -> str:
    """Pick the highest priority type among ``candidates``."""
    return next(name for name in TYPE_PRIORITY if name in candidates)


# What a value that arrives already typed can be cast to.  An integer is not a
# candidate for ``bool`` even though the text "1" would be, and a Parquet
# instant is a timestamp rather than whatever its rendering happens to parse as.
_TYPED_CANDIDATES: dict[type, frozenset[str]] = {
    bool: frozenset({"bool", "string"}),
    int: frozenset({"int", "float", "string"}),
    float: frozenset({"float", "string"}),
    Decimal: frozenset({"float", "string"}),
    date: frozenset({"date", "string"}),
    datetime: frozenset({"timestamp", "string"}),
}

# How a typed value is rendered before the parsers see it; anything else,
# including text itself, goes through ``str``.
_CANONICAL_TEXT: dict[type, Callable[..., str]] = {
    bool: _render_bool,
    date: date.isoformat,
    datetime: datetime.isoformat,
    bytes: bytes.decode,
}


def value_candidates(value: FieldValue, among: Iterable[str]) -> set[str]:
    """Narrow ``among`` to the types that can hold ``value``.

    Raw text is typed by parsing it, so a CSV cell or a JSON string may turn
    out to be a date.  Values that arrive typed keep their own type.
    """
    if isinstance(value, str):
        return matching_types(value, among)
    return set(among) & _TYPED_CANDIDATES.get(type(value), frozenset({"string"}))


def canonical_text(value: FieldValue) -> str:
    """Render a typed value as the text its column's parser expects.

    An object or an array renders as its canonical JSON, which is the text a
    failed cast reports and ``--on-type-error=keep-string`` keeps.
    """
    if isinstance(value, (dict, list)):
        return compact_json(value, default=canonical_text)
    render = _CANONICAL_TEXT.get(type(value))
    return render(value) if render else str(value)


def narrow_number(value: FieldValue) -> FieldValue:
    """Prefer ``int`` for a JSON or Parquet number that is whole and fits.

    Anything else, booleans included, is handed back as it came in.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if INT64_MIN <= value <= INT64_MAX and (isinstance(value, int) or value.is_integer()):
        return int(value)
    return float(value)
