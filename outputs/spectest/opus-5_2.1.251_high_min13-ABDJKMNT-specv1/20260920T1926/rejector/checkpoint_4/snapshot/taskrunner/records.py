"""Shaping outcomes into JSONL rows and the run summary.

A row is written in the Part 1 single-solution shape unless the task asks for
several solutions or configures ICL, in which case `output` and `meta` become
lists and `result` counts solutions instead of describing one. An agentic
attempt is a loop rather than one call, so its metadata is the loop's totals
and its `result` also reports the iterations and tool calls it spent.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .agentic import AgenticOutcome
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
    loop = outcome.attempts[0].agentic if outcome.attempts else None
    result = {
        "passed": _verdict(kept, config, loop),
        "extracted_answer": kept.evaluation.extracted if kept else None,
        "attempts": len(outcome.attempts),
    }
    if loop is not None:
        result["iterations"] = loop.iterations
        result["tool_calls"] = [call.as_dict() for call in loop.tool_calls]
    if config.evaluation and config.evaluation.judge:
        result["judge_score"] = kept.evaluation.judge_score if kept else None
    return {
        "output": {config.output_field: kept.text} if kept else None,
        "result": result,
        "meta": _single_meta(outcome, loop),
    }


def _verdict(
    kept: AttemptOutcome | None, config: TaskConfig, loop: AgenticOutcome | None
) -> bool | None:
    """A kept solution carries its own verdict; otherwise the row failed.

    Only a row that configures no evaluation and never ran out of agentic
    iterations is left undecided.
    """
    if kept:
        return kept.passed
    if config.evaluation or (loop is not None and loop.hit_limit):
        return False
    return None


def _single_meta(outcome: RowOutcome, loop: AgenticOutcome | None) -> Any:
    """The row's metadata: one loop's totals, or one entry per attempt."""
    if loop is not None:
        return _loop_meta(loop)
    return _one_or_many([_meta(attempt) for attempt in outcome.attempts if attempt.meta])


def _loop_meta(loop: AgenticOutcome) -> dict[str, Any] | None:
    """One agentic loop's totals, aggregated across its iterations."""
    if not loop.metas:
        return None
    return {
        "total_prompt_tokens": sum(meta.prompt_tokens for meta in loop.metas),
        "total_completion_tokens": sum(meta.completion_tokens for meta in loop.metas),
        "total_tokens": sum(meta.total_tokens for meta in loop.metas),
        "latency_ms": loop.latency_ms,
        "finish_reason": loop.finish_reason,
        "iterations_detail": [meta.usage() for meta in loop.metas],
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
        "meta": [_listed_meta(attempt) for attempt in outcome.attempts if attempt.metas],
    }


def _meta(attempt: AttemptOutcome) -> dict[str, Any]:
    """One attempt's metadata, carrying the judge call that scored it."""
    entry = attempt.meta.as_dict()
    if attempt.evaluation.judge_meta is not None:
        entry["judge_meta"] = attempt.evaluation.judge_meta.as_dict()
    return entry


def _listed_meta(attempt: AttemptOutcome) -> dict[str, Any]:
    """One attempt's metadata, or one agentic loop's totals, plus its verdict."""
    entry = _loop_meta(attempt.agentic) if attempt.agentic else _meta(attempt)
    return {**entry, "icl_setup": attempt.icl_setup, "evaluation_passed": attempt.passed}


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
    generated = [meta for attempt in outcome.attempts for meta in attempt.metas]
    judged = [
        attempt.evaluation.judge_meta
        for attempt in outcome.attempts
        if attempt.evaluation.judge_meta is not None
    ]
    return generated + judged
