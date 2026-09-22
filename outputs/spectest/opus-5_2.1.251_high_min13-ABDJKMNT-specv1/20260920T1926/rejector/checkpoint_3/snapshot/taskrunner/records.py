"""Shaping outcomes into JSONL rows and the run summary.

A row is written in the Part 1 single-solution shape unless the task asks for
several solutions or configures ICL, in which case `output` and `meta` become
lists and `result` counts solutions instead of describing one.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .config import TaskConfig
from .generation import AttemptOutcome, RowOutcome


def build_record(
    row: Mapping[str, Any], outcome: RowOutcome, config: TaskConfig
) -> dict[str, Any]:
    """The output object for one input row."""
    shape = _single_record if outcome.legacy else _list_record
    return {"input": dict(row), **shape(outcome, config)}


def _single_record(outcome: RowOutcome, config: TaskConfig) -> dict[str, Any]:
    """Part 1 shape: one output object and one verdict for the kept attempt."""
    kept = outcome.solutions[0] if outcome.solutions else None
    result = {
        "passed": kept.passed if kept else (False if config.evaluation else None),
        "extracted_answer": kept.evaluation.extracted if kept else None,
        "attempts": len(outcome.attempts),
    }
    if config.evaluation and config.evaluation.judge:
        result["judge_score"] = kept.evaluation.judge_score if kept else None
    entries = [_meta(attempt) for attempt in outcome.attempts if attempt.meta]
    return {
        "output": {config.output_field: kept.text} if kept else None,
        "result": result,
        "meta": _one_or_many(entries),
    }


def _list_record(outcome: RowOutcome, config: TaskConfig) -> dict[str, Any]:
    """Multi-solution shape: every kept solution, and every attempt's metadata."""
    attempts = len(outcome.attempts)
    passed = outcome.passed_count
    return {
        "output": [
            {config.output_field: solution.text, "icl_setup": solution.icl_setup}
            for solution in outcome.solutions
        ],
        "result": {"passed": passed, "failed": attempts - passed, "attempts": attempts},
        "meta": [_listed_meta(attempt) for attempt in outcome.attempts if attempt.meta],
    }


def _meta(attempt: AttemptOutcome) -> dict[str, Any]:
    """One attempt's metadata, carrying the judge call that scored it."""
    entry = attempt.meta.as_dict()
    if attempt.evaluation.judge_meta is not None:
        entry["judge_meta"] = attempt.evaluation.judge_meta.as_dict()
    return entry


def _listed_meta(attempt: AttemptOutcome) -> dict[str, Any]:
    return {
        **_meta(attempt),
        "icl_setup": attempt.icl_setup,
        "evaluation_passed": attempt.passed,
    }


def _one_or_many(entries: list[dict[str, Any]]) -> Any:
    """One object for a single-attempt row, a list once attempts pile up."""
    if not entries:
        return None
    return entries[0] if len(entries) == 1 else entries


def build_summary(
    results: Mapping[str, Sequence[RowOutcome]], elapsed: float, per_task: bool
) -> dict[str, Any]:
    """Aggregate counters printed to stdout when the run finishes.

    `per_task` adds the `tasks` object; single-task configs keep the Part 1
    key set exactly.
    """
    outcomes = [outcome for task in results.values() for outcome in task]
    metas = [meta for outcome in outcomes for meta in _all_metas(outcome)]
    api_calls = sum(outcome.api_calls for outcome in outcomes)
    summary = {
        **_counters(outcomes),
        "total_prompt_tokens": sum(meta.prompt_tokens for meta in metas),
        "total_completion_tokens": sum(meta.completion_tokens for meta in metas),
        "total_api_calls": api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(api_calls / elapsed * 60, 1) if elapsed else 0.0,
    }
    if per_task:
        summary["tasks"] = {name: _task_summary(task) for name, task in results.items()}
    return summary


def _task_summary(outcomes: Sequence[RowOutcome]) -> dict[str, Any]:
    """Per-task counters, including the solutions its rows produced."""
    solutions = sum(len(outcome.solutions) for outcome in outcomes)
    return {
        **_counters(outcomes),
        "total_solutions": solutions,
        "avg_solutions_per_input": round(solutions / len(outcomes), 2) if outcomes else 0.0,
        "total_api_calls": sum(outcome.api_calls for outcome in outcomes),
    }


def _counters(outcomes: Sequence[RowOutcome]) -> dict[str, int]:
    """A row passes once it has one accepted solution; every other row failed."""
    passed = sum(1 for outcome in outcomes if outcome.passed_count)
    return {"total": len(outcomes), "passed": passed, "failed": len(outcomes) - passed}


def _all_metas(outcome: RowOutcome) -> list[Any]:
    """Generation and judge metadata alike; both are API calls of the run."""
    generated = [attempt.meta for attempt in outcome.attempts if attempt.meta]
    judged = [
        attempt.evaluation.judge_meta
        for attempt in outcome.attempts
        if attempt.evaluation.judge_meta is not None
    ]
    return generated + judged
