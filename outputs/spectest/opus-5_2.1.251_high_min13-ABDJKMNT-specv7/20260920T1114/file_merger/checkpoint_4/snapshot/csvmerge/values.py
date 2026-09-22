"""Values that arrive already typed, from JSON Lines or Parquet.

Casting is defined over text, so a typed value is first spelled the way the CSV
dialect would have spelled it; inference instead reads the value's own type,
which is what makes a typed source worth preferring (ambiguity T27).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from csvmerge.types import candidate_types

_RENDERERS = {
    bool: lambda value: "true" if value else "false",
    float: repr,
    bytes: lambda value: value.decode("utf-8"),
    date: date.isoformat,
    datetime: datetime.isoformat,
}

_CANDIDATES = {
    bool: {"bool"},
    int: {"int", "float"},
    float: {"float"},
    Decimal: {"float"},
    date: {"date"},
    datetime: {"timestamp"},
}


def canonical_text(value: object) -> str:
    """Spell a typed value as text, ready for the target type's cast rules."""
    return _RENDERERS.get(type(value), str)(value)


def typed_candidates(value: object) -> set[str]:
    """The types `value` is evidence for; a string is re-read as text would be."""
    if isinstance(value, str):
        return candidate_types(value)
    return _CANDIDATES.get(type(value), set()) | {"string"}
