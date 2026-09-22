"""Answer extraction and response evaluation."""

from __future__ import annotations

import re

from .config import Evaluation

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def extract_answer(text: str, method: str) -> str | None:
    """Pull the comparison value out of a response."""
    if method == "last_number":
        numbers = _NUMBER.findall(text)
        return numbers[-1] if numbers else None
    if method == "last_line":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else None
    return text


class Evaluator:
    """Judges responses for one configured evaluation."""

    def __init__(self, evaluation: Evaluation):
        self._evaluation = evaluation
        self._pattern = re.compile(evaluation.pattern) if evaluation.type == "regex" else None

    def evaluate(self, text: str, row: dict) -> tuple[bool, str | None]:
        """Return whether the response passes, and the extracted value."""
        extracted = extract_answer(text, self._evaluation.extract)
        if self._evaluation.type == "regex":
            return self._pattern.search(text) is not None, extracted

        expected = str(row[self._evaluation.answer_field])
        if self._evaluation.type == "contains":
            return expected in text, extracted
        return _matches(extracted, expected), extracted


def _matches(extracted: str | None, expected: str) -> bool:
    """Exact-match comparison, treating equal numbers as equal values."""
    if extracted is None:
        return False
    if extracted.strip() == expected.strip():
        return True
    left, right = _as_number(extracted), _as_number(expected)
    return left is not None and left == right


def _as_number(value: str) -> float | None:
    try:
        return float(value.strip().replace(",", ""))
    except ValueError:
        return None
