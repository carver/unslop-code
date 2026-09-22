"""Pulling the comparison value out of a response with the configured extract method."""

import re
from typing import Callable

#: Integers and decimals, with optional thousands separators ("42", "-3.5", "1,234").
NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
#: A standalone multiple-choice letter, so "B", "(B)", "B)" and "Answer: B" all match.
LETTER_RE = re.compile(r"\b([A-D])\b")


def extract_answer(method: str, text: str) -> str | None:
    """Pull the comparison value out of a response using the configured extract method."""
    return _EXTRACTORS[method](text)


def as_number(value: str | None) -> float | None:
    """Parse a fully numeric string, or return ``None`` for anything else."""
    if value is None:
        return None
    return float(value.replace(",", "")) if NUMBER_RE.fullmatch(value.strip()) else None


def _last_number(text: str) -> str | None:
    matches = NUMBER_RE.findall(text)
    return matches[-1].replace(",", "") if matches else None


def _first_number(text: str) -> str | None:
    match = NUMBER_RE.search(text)
    return match.group().replace(",", "") if match else None


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _letter(text: str) -> str | None:
    match = LETTER_RE.search(text)
    return match.group(1) if match else None


_EXTRACTORS: dict[str, Callable[[str], str | None]] = {
    "last_number": _last_number,
    "first_number": _first_number,
    "last_line": _last_line,
    "letter": _letter,
    "full": lambda text: text,
}
