"""Type inference for CSV cells.

Strings stay text, integer and decimal literals become JSON numbers, and
anything else - including time-like values such as `08:30` - is left alone.
"""

import re

Value = str | int | float

INTEGER = re.compile(r"[+-]?\d+\Z")
DECIMAL = re.compile(r"[+-]?(\d+\.\d*|\.\d+|\d+)[eE][+-]?\d+\Z|[+-]?(\d+\.\d*|\.\d+)\Z")


def infer_value(cell: str) -> Value:
    """Convert a raw cell to its JSON type, keeping the original text otherwise."""
    literal = cell.strip()
    if INTEGER.match(literal):
        return int(literal)
    if DECIMAL.match(literal):
        return float(literal)
    return cell


def as_number(value: Value) -> float | None:
    """The numeric reading of a value, or `None` when it does not parse as a float."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except ValueError:
        return None


def as_text(value: Value) -> str:
    """The textual reading of a stored cell, used by the string comparators (T25)."""
    return value if isinstance(value, str) else str(value)
