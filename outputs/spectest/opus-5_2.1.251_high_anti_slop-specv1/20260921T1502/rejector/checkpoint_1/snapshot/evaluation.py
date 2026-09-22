"""Answer extraction and response evaluation."""

from __future__ import annotations

import re

from config import Evaluation
from errors import UsageError

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

Verdict = tuple[bool | None, str | None]


def judge(evaluation: Evaluation | None, text: str, row: dict) -> Verdict:
    """Return `(passed, extracted_answer)`, or `(None, None)` when no evaluation is configured."""
    if evaluation is None:
        return None, None
    return _EVALUATORS[evaluation.type](evaluation, text, row)


def extract(text: str, method: str) -> str | None:
    """Pull the comparison value out of a response."""
    return _EXTRACTORS[method](text)


def require_answer_fields(evaluation: Evaluation | None, rows: list[dict]) -> None:
    """Fail fast when a row lacks the field the evaluation compares against."""
    if evaluation is None or evaluation.answer_field is None:
        return
    for index, row in enumerate(rows):
        if evaluation.answer_field not in row:
            raise UsageError(
                f"row {index}: missing evaluation field '{evaluation.answer_field}'"
            )


def _last_number(text: str) -> str | None:
    numbers = _NUMBER.findall(text)
    return numbers[-1] if numbers else None


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


_EXTRACTORS = {
    "last_number": _last_number,
    "last_line": _last_line,
    "full": str.strip,
}


def _exact_match(evaluation: Evaluation, text: str, row: dict) -> Verdict:
    extracted = extract(text, evaluation.extract)
    expected = str(row[evaluation.answer_field]).strip()
    return extracted == expected, extracted


def _contains(evaluation: Evaluation, text: str, row: dict) -> Verdict:
    expected = str(row[evaluation.answer_field])
    found = expected in text
    return found, expected if found else None


def _regex(evaluation: Evaluation, text: str, row: dict) -> Verdict:
    match = evaluation.pattern.search(text)
    if match is None:
        return False, None
    # A capturing group names the answer explicitly; otherwise the whole match is it.
    return True, match[1] if match.groups() else match[0]


_EVALUATORS = {
    "exact_match": _exact_match,
    "contains": _contains,
    "regex": _regex,
}
