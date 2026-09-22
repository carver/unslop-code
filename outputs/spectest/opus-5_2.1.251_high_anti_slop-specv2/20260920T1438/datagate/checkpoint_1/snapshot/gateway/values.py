"""Deterministic conversion of CSV cells into JSON-friendly values."""

import re

Value = str | int | float

INTEGER = re.compile(r"[+-]?\d+\Z")
DECIMAL = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+)\Z")


def coerce(cell: str) -> Value:
    """Return ``cell`` as a number when it is a plain integer or decimal.

    Anything else stays text, including time-like values such as ``08:30``
    and numeric notations that JSON cannot express (``1e9``, ``NaN``).
    """
    candidate = cell.strip()
    if INTEGER.match(candidate):
        return int(candidate)
    if DECIMAL.match(candidate):
        return float(candidate)
    return cell


def coerce_rows(rows: list[list[str]]) -> list[list[Value]]:
    """Apply :func:`coerce` to every cell, preserving row and column order."""
    return [[coerce(cell) for cell in row] for row in rows]
