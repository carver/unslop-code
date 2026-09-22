"""Conversion of raw CSV cells into the JSON types exposed by the API."""

import re

INTEGER = re.compile(r"[+-]?\d+")
DECIMAL = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?")

Value = str | int | float


def coerce(cell: str) -> Value:
    """Return ``cell`` as a JSON number when it is plainly numeric, otherwise as text.

    Only complete integer and decimal literals become numbers, so time-like cells such
    as ``08:30`` or ``9:15`` -- and anything else with extra characters -- stay text.
    """
    value = cell.strip()
    if INTEGER.fullmatch(value):
        return int(value)
    if DECIMAL.fullmatch(value):
        return float(value)
    return value


def sort_key(value: Value) -> tuple[int, float, str]:
    """Return an ordering key that keeps a column of mixed types comparable.

    Numbers sort among themselves and ahead of text, so a column where type inference
    produced both (``3`` and ``n/a``, say) still has one definite order.
    """
    if isinstance(value, str):
        return (1, 0.0, value)
    return (0, value, "")
