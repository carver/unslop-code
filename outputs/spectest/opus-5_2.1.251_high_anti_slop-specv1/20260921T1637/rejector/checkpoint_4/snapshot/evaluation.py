"""Pass/fail checks: text comparisons, shell commands, and LLM-as-judge scoring."""

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from api import ModelClient
from config import EvaluationConfig
from extraction import as_number, extract_answer
from judge import judge_response
from results import CallMeta
from script_eval import run_command

Row = dict[str, Any]


@dataclass(frozen=True)
class EvalResult:
    """The verdict for one response, with whatever extra the check reported."""

    passed: bool | None
    extracted_answer: str | None
    judge_score: float | int | None = None
    judge_meta: CallMeta | None = None


async def evaluate(
    config: EvaluationConfig | None, text: str, row: Row, judge: ModelClient | None
) -> EvalResult:
    """Judge one response, yielding an empty verdict when no evaluation is configured."""
    if config is None:
        return EvalResult(passed=None, extracted_answer=None)
    return await _CHECKS[config.type](config, text, row, judge)


async def _exact_match(config: EvaluationConfig, text: str, row: Row, judge: ModelClient | None) -> EvalResult:
    extracted = extract_answer(config.extract, text)
    return EvalResult(_same_value(extracted, row[config.answer_field]), extracted)


async def _contains(config: EvaluationConfig, text: str, row: Row, judge: ModelClient | None) -> EvalResult:
    return EvalResult(str(row[config.answer_field]) in text, extract_answer(config.extract, text))


async def _regex(config: EvaluationConfig, text: str, row: Row, judge: ModelClient | None) -> EvalResult:
    return EvalResult(re.search(config.pattern, text) is not None, extract_answer(config.extract, text))


async def _script(config: EvaluationConfig, text: str, row: Row, judge: ModelClient | None) -> EvalResult:
    return EvalResult(await run_command(config, text, row), extract_answer(config.extract, text))


async def _llm_judge(config: EvaluationConfig, text: str, row: Row, judge: ModelClient | None) -> EvalResult:
    """Score the response with the judge model; ``extracted_answer`` is the judge's own answer."""
    verdict = await judge_response(judge, config, text, row)
    return EvalResult(verdict.passed, verdict.extracted, verdict.score, verdict.meta)


def _same_value(extracted: str | None, expected: Any) -> bool:
    """Compare numerically when both sides are numbers, otherwise as trimmed text."""
    if extracted is None:
        return False
    left, right = extracted.strip(), str(expected).strip()
    left_number, right_number = as_number(left), as_number(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return left == right


_CHECKS: dict[str, Callable[[EvaluationConfig, str, Row, ModelClient | None], Awaitable[EvalResult]]] = {
    "exact_match": _exact_match,
    "contains": _contains,
    "regex": _regex,
    "script": _script,
    "llm_judge": _llm_judge,
}
