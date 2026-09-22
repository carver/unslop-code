"""Type inference for CSV cells.

Strings stay text, integer and decimal literals become JSON numbers, and
anything else - including time-like values such as `08:30` - is left alone.
"""

import re

INTEGER = re.compile(r"[+-]?\d+\Z")
DECIMAL = re.compile(r"[+-]?(\d+\.\d*|\.\d+|\d+)[eE][+-]?\d+\Z|[+-]?(\d+\.\d*|\.\d+)\Z")


def infer_value(cell: str) -> str | int | float:
    """Convert a raw cell to its JSON type, keeping the original text otherwise."""
    literal = cell.strip()
    if INTEGER.match(literal):
        return int(literal)
    if DECIMAL.match(literal):
        return float(literal)
    return cell
