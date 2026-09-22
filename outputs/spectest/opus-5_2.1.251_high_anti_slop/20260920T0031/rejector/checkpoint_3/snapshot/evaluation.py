"""Answer extraction and the pass/fail checks computed from a response on its own.

The two evaluation types that reach outside this module — `llm_judge` (a second
model call) and `script` (a shell command) — are implemented in `judge.py` and
`script_eval.py`; only their names and configuration live here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from templates import PromptConfig

NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
#: A multiple-choice letter standing on its own, as in `B`, `(B)`, `B)` or `Answer: B`.
LETTER_PATTERN = re.compile(r"(?<![A-Za-z0-9])([A-D])(?![A-Za-z0-9])")

LLM_JUDGE = "llm_judge"
SCRIPT = "script"


@dataclass(frozen=True)
class EvaluationConfig:
    """How a response is scored; the trailing fields belong to one evaluation type each."""

    type: str
    extract: str
    answer_field: str | None = None
    pattern: re.Pattern[str] | None = None
    judge_prompt: PromptConfig | None = None
    threshold: float | None = None
    model: str | None = None
    command_template: str | None = None
    success_exit_code: int = 0


@dataclass(frozen=True)
class Outcome:
    """Result of evaluating one response; `passed` is None when no evaluation runs."""

    passed: bool | None
    extracted: str | None
    judge_score: float | None = None
    judge_meta: dict[str, Any] | None = None


NO_EVALUATION = Outcome(passed=None, extracted=None)


def _last_number(text: str) -> str | None:
    matches = NUMBER_PATTERN.findall(text)
    return matches[-1] if matches else None


def _first_number(text: str) -> str | None:
    match = NUMBER_PATTERN.search(text)
    return match.group() if match else None


def _letter(text: str) -> str | None:
    match = LETTER_PATTERN.search(text)
    return match.group(1) if match else None


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _full(text: str) -> str:
    return text.strip()


EXTRACTORS: dict[str, Callable[[str], str | None]] = {
    "last_number": _last_number,
    "first_number": _first_number,
    "letter": _letter,
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

#: Every configurable evaluation type, including the two run outside this module.
EVALUATION_TYPES = frozenset(CHECKS) | {LLM_JUDGE, SCRIPT}

#: Evaluation types that compare against a field of the input row.
ANSWER_FIELD_TYPES = frozenset({"exact_match", "contains"})


def evaluate(text: str, row: dict[str, Any], config: EvaluationConfig) -> Outcome:
    """Score one response with a check that needs nothing but the response text."""
    extracted = EXTRACTORS[config.extract](text)
    return Outcome(passed=CHECKS[config.type](text, extracted, config, row), extracted=extracted)
