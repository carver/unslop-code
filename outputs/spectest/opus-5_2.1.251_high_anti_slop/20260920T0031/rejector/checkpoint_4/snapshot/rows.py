"""The JSONL result row written for one finished input row.

A task asking for a single solution without ICL keeps the Part 1 shape: one
`output` object and the outcome of its last attempt. Every other task reports a
list of solutions, each tagged with the ICL setup that produced it, and one
metadata entry per attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import TaskConfig
from endpoints import Completion
from evaluation import LLM_JUDGE, Outcome

Result = dict[str, Any]


@dataclass(frozen=True)
class Attempt:
    """One generation attempt: what it produced, under which ICL setup, and how it scored."""

    completion: Completion | None
    icl_setup: str | None
    outcome: Outcome
    #: Whether the response is kept as a solution; rejection sampling drops failures.
    kept: bool
    #: API requests an agentic loop spent on this attempt, and the tool calls it made.
    iterations: int = 0
    tool_calls: tuple[dict[str, Any], ...] = ()

    @property
    def meta(self) -> dict[str, Any] | None:
        """The attempt's metadata, or None when the retry budget ran out before an answer."""
        if self.completion is None:
            return None
        if self.outcome.judge_meta is None:
            return self.completion.meta
        return {**self.completion.meta, "judge_meta": self.outcome.judge_meta}


def single_row(task: TaskConfig, row: dict[str, Any], attempts: list[Attempt]) -> Result:
    """The Part 1 row: the last attempt's response, its score and its metadata.

    An agentic task adds the loop's iteration count and the tools it called.
    """
    metas = [attempt.meta for attempt in attempts if attempt.meta is not None]
    last = attempts[-1]
    output = {task.output_field: last.completion.text} if last.kept else None
    result = {
        "passed": None if task.evaluation is None else (output is not None and last.outcome.passed is True),
        "extracted_answer": last.outcome.extracted if output is not None else None,
        "attempts": max(len(metas), 1),
    }
    if task.agentic:
        result["iterations"] = last.iterations
        result["tool_calls"] = list(last.tool_calls)
    if _judged(task):
        result["judge_score"] = last.outcome.judge_score if output is not None else None
    return {"input": row, "output": output, "result": result, "meta": _single_meta(metas)}


def multi_row(task: TaskConfig, row: dict[str, Any], attempts: list[Attempt]) -> Result:
    """The list row: every kept solution, the pass/fail counts and per-attempt metadata."""
    outputs = [
        {task.output_field: attempt.completion.text, "icl_setup": attempt.icl_setup}
        for attempt in attempts
        if attempt.kept
    ]
    passed = _passed_count(task, attempts, len(outputs))
    return {
        "input": row,
        "output": outputs,
        "result": {"passed": passed, "failed": len(attempts) - passed, "attempts": len(attempts)},
        "meta": [
            {**attempt.meta, "icl_setup": attempt.icl_setup, "evaluation_passed": attempt.outcome.passed}
            for attempt in attempts
            if attempt.meta is not None
        ],
    }


def _passed_count(task: TaskConfig, attempts: list[Attempt], emitted: int) -> int:
    """Attempts that passed evaluation, or the solutions emitted when nothing evaluates them."""
    if task.evaluation is None:
        return emitted
    return sum(1 for attempt in attempts if attempt.outcome.passed is True)


def _judged(task: TaskConfig) -> bool:
    return task.evaluation is not None and task.evaluation.type == LLM_JUDGE


def _single_meta(metas: list[dict[str, Any]]) -> Any:
    """A single metadata object for one-attempt rows, a list for multi-attempt ones."""
    if len(metas) == 1:
        return metas[0]
    return metas or None
