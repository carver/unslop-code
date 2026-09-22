"""Answer extraction and pass/fail checks applied to model responses."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class EvaluationConfig:
    """How a response is scored. `pattern` is only used by the `regex` type."""

    type: str
    extract: str
    answer_field: str | None = None
    pattern: re.Pattern[str] | None = None


@dataclass(frozen=True)
class Outcome:
    """Result of evaluating one response; `passed` is None when no evaluation runs."""

    passed: bool | None
    extracted: str | None


NO_EVALUATION = Outcome(passed=None, extracted=None)


def _last_number(text: str) -> str | None:
    matches = NUMBER_PATTERN.findall(text)
    return matches[-1] if matches else None


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _full(text: str) -> str:
    return text.strip()


EXTRACTORS: dict[str, Callable[[str], str | None]] = {
    "last_number": _last_number,
    "last_line": _last_line,
    "full": _full,
}


def _normalize(value: Any) -> str:
    """Comparable form: numbers compare by value, other text case-insensitively."""
    text = str(value).strip().replace(",", "")
    if NUMBER_PATTERN.fullmatch(text):
        return format(float(text), "g")
    return text.lower()


def _exact_match(text: str, extracted: str | None, config: EvaluationConfig, row: dict[str, Any]) -> bool:
    return extracted is not None and _normalize(extracted) == _normalize(row[config.answer_field])


def _contains(text: str, extracted: str | None, config: EvaluationConfig, row: dict[str, Any]) -> bool:
    return str(row[config.answer_field]) in text


def _regex(text: str, extracted: str | None, config: EvaluationConfig, row: dict[str, Any]) -> bool:
    return config.pattern.search(text) is not None


Check = Callable[[str, str | None, EvaluationConfig, dict[str, Any]], bool]

CHECKS: dict[str, Check] = {
    "exact_match": _exact_match,
    "contains": _contains,
    "regex": _regex,
}

#: Evaluation types that compare against a field of the input row.
ANSWER_FIELD_TYPES = frozenset({"exact_match", "contains"})


def evaluate(text: str, row: dict[str, Any], config: EvaluationConfig | None) -> Outcome:
    """Score one response against its input row, or return NO_EVALUATION when unconfigured."""
    if config is None:
        return NO_EVALUATION
    extracted = EXTRACTORS[config.extract](text)
    return Outcome(passed=CHECKS[config.type](text, extracted, config, row), extracted=extracted)
