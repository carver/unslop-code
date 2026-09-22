"""Answer extraction and the five evaluation types."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .api import CallMeta, ChatClient
from .config import EvaluationConfig
from .judge import ask_judge, to_score
from .script_eval import run_script

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
# An answer choice is a standalone A-D, so `(A)`, `A)` and `Answer: A` all
# match while `Alpha` and `ANSWER` do not.
CHOICE = re.compile(r"(?<![A-Za-z0-9])([A-D])(?![A-Za-z0-9])")


@dataclass(frozen=True)
class EvalOutcome:
    """The verdict on one response, plus what judging it cost."""

    passed: bool | None
    extracted: str | None
    judge_score: float | None = None
    judge_meta: CallMeta | None = None
    api_calls: int = 0


def extract_answer(text: str, method: str) -> str | None:
    """Reduce a response to the value an evaluation compares against."""
    return _EXTRACTORS[method](text)


def _last_number(text: str) -> str | None:
    matches = NUMBER.findall(text)
    return matches[-1] if matches else None


def _first_number(text: str) -> str | None:
    match = NUMBER.search(text)
    return match.group(0) if match else None


def _letter(text: str) -> str | None:
    match = CHOICE.search(text)
    return match.group(1) if match else None


def _last_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


_EXTRACTORS = {
    "last_number": _last_number,
    "first_number": _first_number,
    "letter": _letter,
    "last_line": _last_line,
    "full": lambda text: text,
}


async def evaluate(
    text: str,
    row: Mapping[str, Any],
    config: EvaluationConfig | None,
    judge_client: ChatClient | None,
) -> EvalOutcome:
    """Judge one response against the task's evaluation.

    `passed` and `extracted` are `None` when the task configures no
    evaluation. `judge_client` is only used by `llm_judge` tasks.
    """
    if config is None:
        return EvalOutcome(passed=None, extracted=None)
    return await _EVALUATORS[config.type](text, row, config, judge_client)


async def _text_check(
    text: str,
    row: Mapping[str, Any],
    config: EvaluationConfig,
    judge_client: ChatClient | None,
) -> EvalOutcome:
    """The Part 1 types: extract a comparison value, then compare it."""
    extracted = extract_answer(text, config.extract)
    passed = _CHECKS[config.type](text, extracted, row, config)
    return EvalOutcome(passed=passed, extracted=extracted)


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


async def _script_check(
    text: str,
    row: Mapping[str, Any],
    config: EvaluationConfig,
    judge_client: ChatClient | None,
) -> EvalOutcome:
    passed = await run_script(config.script, row, text)
    return EvalOutcome(passed=passed, extracted=extract_answer(text, config.extract))


async def _judge_check(
    text: str,
    row: Mapping[str, Any],
    config: EvaluationConfig,
    judge_client: ChatClient | None,
) -> EvalOutcome:
    """Score the response with a second model call; no score means no pass."""
    call = await ask_judge(judge_client, config.judge, row, text)
    extracted = None if call.text is None else extract_answer(call.text, config.extract)
    score = to_score(extracted)
    return EvalOutcome(
        passed=score is not None and score >= config.judge.threshold,
        extracted=extracted,
        judge_score=score,
        judge_meta=call.meta,
        api_calls=call.requests,
    )


_EVALUATORS = {
    "exact_match": _text_check,
    "contains": _text_check,
    "regex": _text_check,
    "script": _script_check,
    "llm_judge": _judge_check,
}
