"""Pulling the comparison value out of a model response."""

from __future__ import annotations

import re

_NUMBER = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
_CHOICE = re.compile(r"\b([A-D])\b")


def _pick(values: list[str], index: int) -> str | None:
    """The value at `index`, or None when there was nothing to extract."""
    return values[index] if values else None


def _number(values: list[str], index: int) -> str | None:
    """One matched number, with the thousands separators taken back out."""
    picked = _pick(values, index)
    return None if picked is None else picked.replace(",", "")


_EXTRACTORS = {
    "last_number": lambda text: _number(_NUMBER.findall(text), -1),
    "first_number": lambda text: _number(_NUMBER.findall(text), 0),
    "letter": lambda text: _pick(_CHOICE.findall(text), 0),
    "last_line": lambda text: _pick([line.strip() for line in text.splitlines() if line.strip()], -1),
    "full": lambda text: text,
}

EXTRACT_METHODS = tuple(_EXTRACTORS)


def extract_answer(text: str, method: str) -> str | None:
    """Apply one extract method to a response.

    `letter` looks for a standalone uppercase `A`-`D`, which covers the bare
    letter as well as the `(A)`, `A)` and `Answer: A` forms without matching
    a capital that merely starts a word.  The number methods read comma
    grouped figures such as `$2,730,000` as the single value `2730000`.
    """
    return _EXTRACTORS[method](text)


def as_number(value: str) -> float | None:
    """Parse a numeric comparison value, or None when it is not a number."""
    try:
        return float(value.strip().replace(",", ""))
    except ValueError:
        return None
