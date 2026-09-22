"""Answer extraction and response evaluation."""

from __future__ import annotations

import re

from .config import EvaluationConfig

NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def extract_answer(text: str, method: str) -> str | None:
    """Pull the comparison value out of `text`, or None when there is none."""
    if method == "last_number":
        numbers = NUMBER_PATTERN.findall(text)
        return numbers[-1] if numbers else None
    if method == "last_line":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else None
    return text


def evaluate_response(
    text: str, evaluation: EvaluationConfig, row: dict
) -> tuple[bool, str | None]:
    """Score `text` against `evaluation`, returning (passed, extracted answer).

    The extracted answer is reported for every evaluation type, while
    `contains` and `regex` match against the response text itself as specified.
    """
    extracted = extract_answer(text, evaluation.extract)
    if evaluation.type == "exact_match":
        expected = str(row[evaluation.answer_field]).strip()
        return extracted is not None and extracted.strip() == expected, extracted
    if evaluation.type == "contains":
        return str(row[evaluation.answer_field]) in text, extracted
    return re.search(evaluation.pattern, text) is not None, extracted
