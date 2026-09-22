"""Answer extraction and the three evaluation types."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .config import EvaluationConfig

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def extract_answer(text: str, method: str) -> str | None:
    """Reduce a response to the value an evaluation compares against."""
    return _EXTRACTORS[method](text)


def _last_number(text: str) -> str | None:
    matches = NUMBER.findall(text)
    return matches[-1] if matches else None


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


_EXTRACTORS = {
    "last_number": _last_number,
    "last_line": _last_line,
    "full": lambda text: text,
}


def evaluate(
    text: str, row: Mapping[str, Any], config: EvaluationConfig | None
) -> tuple[bool | None, str | None]:
    """Return `(passed, extracted_answer)` for one response.

    Both are `None` when the task configures no evaluation.
    """
    if config is None:
        return None, None
    extracted = extract_answer(text, config.extract)
    return _CHECKS[config.type](text, extracted, row, config), extracted


def _exact_match(
    text: str, extracted: str | None, row: Mapping[str, Any], config: EvaluationConfig
) -> bool:
    if extracted is None:
        return False
    return extracted.strip() == str(row[config.answer_field]).strip()


def _contains(
    text: str, extracted: str | None, row: Mapping[str, Any], config: EvaluationConfig
) -> bool:
    return str(row[config.answer_field]) in text


def _regex(
    text: str, extracted: str | None, row: Mapping[str, Any], config: EvaluationConfig
) -> bool:
    return re.search(config.pattern, text) is not None


_CHECKS = {"exact_match": _exact_match, "contains": _contains, "regex": _regex}
