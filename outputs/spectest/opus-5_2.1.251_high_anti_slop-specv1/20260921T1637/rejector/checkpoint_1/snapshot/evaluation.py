"""Answer extraction from responses and the pass/fail checks built on top of it."""

import re
from typing import Any, Callable

from config import EvaluationConfig

#: Integers and decimals, with optional thousands separators ("42", "-3.5", "1,234").
NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


def evaluate(
    config: EvaluationConfig | None, text: str, row: dict[str, Any]
) -> tuple[bool | None, str | None]:
    """Return ``(passed, extracted_answer)``, or ``(None, None)`` when no evaluation is configured."""
    if config is None:
        return None, None
    extracted = extract_answer(config.extract, text)
    return _CHECKS[config.type](config, text, extracted, row), extracted


def extract_answer(method: str, text: str) -> str | None:
    """Pull the comparison value out of a response using the configured extract method."""
    return _EXTRACTORS[method](text)


def _last_number(text: str) -> str | None:
    matches = NUMBER_RE.findall(text)
    return matches[-1].replace(",", "") if matches else None


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _exact_match(config: EvaluationConfig, text: str, extracted: str | None, row: dict[str, Any]) -> bool:
    return _same_value(extracted, row[config.answer_field])


def _contains(config: EvaluationConfig, text: str, extracted: str | None, row: dict[str, Any]) -> bool:
    return str(row[config.answer_field]) in text


def _regex(config: EvaluationConfig, text: str, extracted: str | None, row: dict[str, Any]) -> bool:
    return re.search(config.pattern, text) is not None


def _same_value(extracted: str | None, expected: Any) -> bool:
    """Compare numerically when both sides are numbers, otherwise as trimmed text."""
    if extracted is None:
        return False
    left, right = extracted.strip(), str(expected).strip()
    left_number, right_number = _as_number(left), _as_number(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return left == right


def _as_number(value: str) -> float | None:
    return float(value.replace(",", "")) if NUMBER_RE.fullmatch(value) else None


_EXTRACTORS: dict[str, Callable[[str], str | None]] = {
    "last_number": _last_number,
    "last_line": _last_line,
    "full": lambda text: text,
}

_CHECKS: dict[str, Callable[[EvaluationConfig, str, str | None, dict[str, Any]], bool]] = {
    "exact_match": _exact_match,
    "contains": _contains,
    "regex": _regex,
}
