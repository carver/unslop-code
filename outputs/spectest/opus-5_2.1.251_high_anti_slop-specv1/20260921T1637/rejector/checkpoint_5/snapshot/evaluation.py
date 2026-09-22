"""Pass/fail checks: schema validation, text comparisons, shell commands, and judge scoring."""

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from api import ModelClient
from config import EvaluationConfig, TaskConfig
from extraction import as_number, extract_answer
from judge import judge_response
from output_schema import check_output
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


@dataclass(frozen=True)
class Verdict:
    """Everything decided about one response: its output value and how it fared.

    ``output`` is what the row should report — the response text, or the parsed
    document when the task has an ``output_schema`` — and ``None`` when the
    response cannot be used. ``schema_valid`` and ``schema_error`` stay ``None``
    for tasks that declare no schema.
    """

    output: Any
    passed: bool | None
    extracted_answer: str | None = None
    judge_score: float | int | None = None
    judge_meta: CallMeta | None = None
    schema_valid: bool | None = None
    schema_error: str | None = None


async def grade(task: TaskConfig, text: str, row: Row, judge: ModelClient | None) -> Verdict:
    """Validate one response against the task's schema, then evaluate it.

    A response that fails the schema is never evaluated: it has no usable
    output and its verdict is a failure. A task with a schema and no evaluation
    passes on any response the schema accepts.
    """
    check = check_output(task.output_schema, text)
    if not check.valid:
        return Verdict(output=None, passed=False, schema_valid=False, schema_error=check.error)

    result = await evaluate(task.evaluation, text, row, judge)
    schema_valid = True if task.output_schema else None
    return Verdict(
        output=check.value,
        passed=result.passed if task.evaluation else schema_valid,
        extracted_answer=result.extracted_answer,
        judge_score=result.judge_score,
        judge_meta=result.judge_meta,
        schema_valid=schema_valid,
    )


def failed_verdict(task: TaskConfig) -> Verdict:
    """The verdict of a row that never produced a response worth keeping."""
    return Verdict(output=None, passed=False if task.graded else None)


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
