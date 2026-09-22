"""Applying a task's evaluation to one response, and the metadata it leaves.

The deterministic evaluations, the `script` command and the `llm_judge` call
all report the same `Verdict`, so both the single-solution and multi-solution
paths score an attempt through here.
"""

from __future__ import annotations

from .api import Channel, Completion
from .config import TaskConfig
from .evaluation import Verdict, evaluate_response
from .judge import judge_response
from .script_eval import run_script

NO_EVALUATION = Verdict(passed=None)


async def score_response(
    text: str, task: TaskConfig, row: dict, channel: Channel
) -> Verdict:
    """Evaluate one response with whichever evaluation the task configures."""
    evaluation = task.evaluation
    if evaluation is None:
        return NO_EVALUATION
    if evaluation.type == "script":
        return Verdict(passed=await run_script(evaluation.script, row, text))
    if evaluation.type == "llm_judge":
        return await judge_response(text, evaluation, row, channel)

    passed, extracted = evaluate_response(text, evaluation, row)
    return Verdict(passed=passed, extracted_answer=extracted)


def attempt_meta(completion: Completion, verdict: Verdict, task: TaskConfig) -> dict:
    """One attempt's metadata, carrying its judge call's metadata when judged."""
    if task.judge is None:
        return completion.meta
    return {**completion.meta, "judge_meta": verdict.judge_meta}
