"""Scoring one response: structured output validation, then the evaluation.

The deterministic evaluations, the `script` command and the `llm_judge` call
all report the same `Verdict`, so both the single-solution and multi-solution
paths score an attempt through here. A task with an `output_schema` validates
first and never evaluates a response that failed validation.
"""

from __future__ import annotations

from dataclasses import replace

from .api import Channel, Completion
from .config import TaskConfig
from .evaluation import Verdict, evaluate_response
from .judge import judge_response
from .schema import parse_and_validate
from .script_eval import run_script

NO_EVALUATION = Verdict(passed=None)


def failure_verdict(task: TaskConfig) -> Verdict:
    """The verdict for a row with no usable output; unscored stays null."""
    return Verdict(passed=None if not task.has_verdict else False)


async def score_response(
    text: str, task: TaskConfig, row: dict, channel: Channel
) -> Verdict:
    """Score one response against the task's schema and its evaluation."""
    if task.output_schema is None:
        return await _evaluate(text, task, row, channel)

    value, error = parse_and_validate(text, task.output_schema)
    if error is not None:
        return Verdict(passed=False, schema_valid=False, schema_error=error)

    verdict = await _evaluate(text, task, row, channel)
    passed = True if verdict.passed is None else verdict.passed
    return replace(verdict, passed=passed, output=value, schema_valid=True)


async def _evaluate(
    text: str, task: TaskConfig, row: dict, channel: Channel
) -> Verdict:
    """Evaluate one response with whichever evaluation the task configures."""
    evaluation = task.evaluation
    if evaluation is None:
        return Verdict(passed=None, output=text)
    if evaluation.type == "script":
        passed = await run_script(evaluation.script, row, text)
        return Verdict(passed=passed, output=text)
    if evaluation.type == "llm_judge":
        return replace(await judge_response(text, evaluation, row, channel), output=text)

    passed, extracted = evaluate_response(text, evaluation, row)
    return Verdict(passed=passed, extracted_answer=extracted, output=text)


def attempt_meta(completion: Completion, verdict: Verdict, task: TaskConfig) -> dict:
    """One attempt's metadata, carrying its judge call's metadata when judged."""
    if task.judge is None:
        return completion.meta
    return {**completion.meta, "judge_meta": verdict.judge_meta}
