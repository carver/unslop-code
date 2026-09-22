"""Answer extraction and pass/fail judgement of model responses."""

from __future__ import annotations

import re
from typing import Any, Callable

from config import EvaluationConfig

_NUMBER = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


def extract_answer(method: str, text: str) -> str | None:
    """Pull the comparison value out of a response, or None if there is none."""
    return _EXTRACTORS[method](text)


def evaluate(
    config: EvaluationConfig | None, text: str, row: dict[str, Any]
) -> tuple[bool | None, str | None]:
    """Judge a response against its input row.

    Returns the pass flag and the extracted comparison value. Both are None when
    no evaluation is configured.
    """
    if config is None:
        return None, None
    extracted = extract_answer(config.extract, text)
    return _CHECKS[config.type](config, text, row, extracted), extracted


def _last_number(text: str) -> str | None:
    matches = _NUMBER.findall(text)
    return matches[-1].replace(",", "") if matches else None


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


_EXTRACTORS: dict[str, Callable[[str], str | None]] = {
    "last_number": _last_number,
    "last_line": _last_line,
    "full": lambda text: text,
}


def _check_exact_match(
    config: EvaluationConfig, text: str, row: dict[str, Any], extracted: str | None
) -> bool:
    return extracted is not None and _same_value(extracted, str(row[config.answer_field]))


def _check_contains(
    config: EvaluationConfig, text: str, row: dict[str, Any], extracted: str | None
) -> bool:
    return str(row[config.answer_field]) in text


def _check_regex(
    config: EvaluationConfig, text: str, row: dict[str, Any], extracted: str | None
) -> bool:
    return re.search(config.pattern, text) is not None


_CHECKS: dict[str, Callable[[EvaluationConfig, str, dict[str, Any], str | None], bool]] = {
    "exact_match": _check_exact_match,
    "contains": _check_contains,
    "regex": _check_regex,
}


def _same_value(extracted: str, expected: str) -> bool:
    """Compare as text, falling back to numeric equality so 8 matches 8.0."""
    if extracted.strip() == expected.strip():
        return True
    try:
        return float(extracted) == float(expected.replace(",", ""))
    except ValueError:
        return False
