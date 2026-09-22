"""Reducing a response to the value an evaluation compares against."""

from __future__ import annotations

import re

# Optional sign, optional thousands groups, optional fractional part (T5).
NUMBER = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?|-?\.\d+")

# An answer choice is a bare A-D, so letters inside words are not choices (T24).
LETTER = re.compile(r"(?<![A-Za-z])([A-D])(?![A-Za-z])")


def extract_answer(text: str, method: str) -> str | None:
    """Apply one extract method to a response, or ``None`` when it finds nothing."""
    return _EXTRACTORS[method](text)


def _number(text: str, index: int) -> str | None:
    numbers = NUMBER.findall(text)
    return numbers[index].replace(",", "") if numbers else None


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _letter(text: str) -> str | None:
    """The first `A`-`D` choice, as written in `A`, `(A)`, `A)` or `Answer: A`."""
    match = LETTER.search(text)
    return match.group(1) if match else None


_EXTRACTORS = {
    "full": lambda text: text,
    "last_line": _last_line,
    "last_number": lambda text: _number(text, -1),
    "first_number": lambda text: _number(text, 0),
    "letter": _letter,
}
