"""Answer extraction and evaluation of a response against its input row."""

from __future__ import annotations

import re

from rejlib.config import Evaluation

# Optional sign, optional thousands groups, optional fractional part (T5).
NUMBER = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?|-?\.\d+")


def extract_answer(text: str, method: str) -> str | None:
    """Reduce a response to the value an evaluation compares against."""
    if method == "full":
        return text
    if method == "last_line":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else None
    numbers = NUMBER.findall(text)
    return numbers[-1].replace(",", "") if numbers else None


def evaluate(evaluation: Evaluation, text: str, row: dict) -> tuple[bool, str | None]:
    """Judge one response, returning ``(passed, extracted_answer)``."""
    extracted = extract_answer(text, evaluation.extract)
    if evaluation.type == "regex":
        return bool(re.search(evaluation.pattern, text)), extracted

    expected = str(row[evaluation.answer_field])
    if evaluation.type == "contains":
        return expected in text, extracted
    return _exact_match(extracted, expected), extracted


def _exact_match(extracted: str | None, expected: str) -> bool:
    """Numbers compare by value, anything else by stripped text (T6)."""
    if extracted is None:
        return False
    numbers = _as_numbers(extracted, expected)
    if numbers is not None:
        return numbers[0] == numbers[1]
    return extracted.strip() == expected.strip()


def _as_numbers(*values: str) -> list[float] | None:
    try:
        return [float(value.replace(",", "").strip()) for value in values]
    except ValueError:
        return None
