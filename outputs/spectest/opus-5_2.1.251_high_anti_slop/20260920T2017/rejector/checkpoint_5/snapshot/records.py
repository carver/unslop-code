"""What one row produced, the output record it becomes, and reading it back.

A row is written in one of two shapes: the single-solution format, or the list
format a task with ICL or several solutions uses. The counts the summary,
progress reporting and resume need are read back out of the written record, so
they agree with the file on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import TaskConfig
from verdicts import Verdict


@dataclass(frozen=True)
class Attempt:
    """One generated response, with the metadata, verdict and setup behind it.

    `output` is what the row records for the attempt: the response text, or the
    parsed JSON value once an `output_schema` has validated it. It is None when
    the attempt produced nothing usable — an agentic loop that hit its iteration
    limit, or a response the schema rejected. `iterations` and `tool_calls` are
    only filled in by the agentic scheme.
    """

    output: Any
    meta: dict[str, Any]
    verdict: Verdict
    setup_name: str | None
    iterations: int | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class RowOutcome:
    """What a single-solution row produced, before it is shaped into a record."""

    output: Any
    verdict: Verdict
    attempts: int
    metas: list[dict[str, Any]]
    iterations: int | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class MultiOutcome:
    """What a multi-solution row produced.

    `solutions` are the attempts kept as output — every answered attempt, or
    only the passing ones under rejection sampling. `completed` holds each
    attempt the API answered, and `attempts` counts those it did not too.
    """

    solutions: list[Attempt]
    completed: list[Attempt]
    attempts: int


def single_record(config: TaskConfig, row: dict[str, Any], outcome: RowOutcome) -> dict[str, Any]:
    # One metadata object for single-attempt rows, a list once rejection sampling
    # made several attempts, and null when no attempt reached the API.
    metas = outcome.metas
    verdict = outcome.verdict
    result = {
        "passed": verdict.passed,
        "extracted_answer": verdict.extracted_answer,
        "attempts": outcome.attempts,
    }
    if verdict.schema_valid is not None:
        result["schema_valid"] = verdict.schema_valid
    if verdict.schema_error is not None:
        result["schema_error"] = verdict.schema_error
    if outcome.iterations is not None:
        result["iterations"] = outcome.iterations
        result["tool_calls"] = outcome.tool_calls
    if config.evaluation and config.evaluation.type == "llm_judge":
        result["judge_score"] = verdict.judge_score
    return {
        "input": row,
        "output": None if outcome.output is None else {config.output_field: outcome.output},
        "result": result,
        "meta": metas[0] if len(metas) == 1 else (metas or None),
    }


def multi_record(config: TaskConfig, row: dict[str, Any], outcome: MultiOutcome) -> dict[str, Any]:
    """The list format: one output object per solution, one metadata per attempt."""
    passed = _passed_count(config, outcome)
    return {
        "input": row,
        "output": [
            {config.output_field: attempt.output, "icl_setup": attempt.setup_name}
            for attempt in outcome.solutions
        ],
        "result": {
            "passed": passed,
            "failed": outcome.attempts - passed,
            "attempts": outcome.attempts,
        },
        "meta": [
            {
                **attempt.meta,
                "icl_setup": attempt.setup_name,
                "evaluation_passed": attempt.verdict.passed,
            }
            for attempt in outcome.completed
        ],
    }


def counts(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The per-row totals the summary reports for a set of records."""
    passed = sum(1 for record in records if is_passed(record))
    solutions = sum(solution_count(record) for record in records)
    total = len(records)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "total_solutions": solutions,
        "avg_solutions_per_input": round(solutions / total, 2) if total else 0.0,
    }


def is_passed(record: dict[str, Any]) -> bool:
    """A row passes once it has produced a solution nothing rejected."""
    if isinstance(record["output"], list):
        return record["result"]["passed"] > 0
    passed = record["result"]["passed"]
    return passed is True or (passed is None and record["output"] is not None)


def solution_count(record: dict[str, Any]) -> int:
    output = record["output"]
    return len(output) if isinstance(output, list) else int(output is not None)


def _passed_count(config: TaskConfig, outcome: MultiOutcome) -> int:
    """Attempts the evaluation accepted, or the emitted solutions when none judges them."""
    if config.evaluation is None:
        return len(outcome.solutions)
    return sum(1 for attempt in outcome.completed if attempt.verdict.passed)
