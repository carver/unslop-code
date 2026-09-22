"""Per-cell type inference.

Only integers and decimals become JSON numbers. The patterns deliberately
reject anything with extra structure, which is what keeps time-like values
(``08:30``, ``9:15``, ``12:00``), dates and percentages as text, and keeps
``nan``/``inf`` -- which are not representable in JSON -- out of the output.
"""

import re

_INTEGER = re.compile(r"[+-]?[0-9]+\Z")
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def coerce_value(text: str) -> str | int | float:
    """Return `text` as an int or float when it is numeric, otherwise unchanged."""
    candidate = text.strip()
    if _INTEGER.match(candidate):
        return int(candidate)
    if _DECIMAL.match(candidate):
        return float(candidate)
    return text
