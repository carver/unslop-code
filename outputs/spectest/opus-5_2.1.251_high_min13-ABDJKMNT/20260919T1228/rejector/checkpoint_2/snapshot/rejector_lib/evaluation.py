"""Answer extraction and the deterministic evaluation types.

`script` and `llm_judge` need to run a command or a second API call, so they
live in their own modules; the runner dispatches to them and they report the
same `Verdict`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import EvaluationConfig

NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
CHOICE_PATTERN = re.compile(r"\b([A-D])\b")


@dataclass(frozen=True)
class Verdict:
    """The outcome of evaluating one response."""

    passed: bool | None
    extracted_answer: str | None = None
    judge_score: float | None = None
    judge_meta: dict | None = None


def extract_answer(text: str, method: str) -> str | None:
    """Pull the comparison value out of `text`, or None when there is none."""
    if method == "last_number":
        numbers = NUMBER_PATTERN.findall(text)
        return numbers[-1] if numbers else None
    if method == "first_number":
        match = NUMBER_PATTERN.search(text)
        return match.group() if match else None
    if method == "letter":
        match = CHOICE_PATTERN.search(text)
        return match.group(1) if match else None
    if method == "last_line":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else None
    return text


def evaluate_response(
    text: str, evaluation: EvaluationConfig, row: dict
) -> tuple[bool, str | None]:
    """Score `text` against `evaluation`, returning (passed, extracted answer).

    The extracted answer is reported for every deterministic evaluation type,
    while `contains` and `regex` match against the response text itself as
    specified.
    """
    extracted = extract_answer(text, evaluation.extract)
    if evaluation.type == "exact_match":
        expected = str(row[evaluation.answer_field]).strip()
        return extracted is not None and extracted.strip() == expected, extracted
    if evaluation.type == "contains":
        return str(row[evaluation.answer_field]) in text, extracted
    return re.search(evaluation.pattern, text) is not None, extracted
