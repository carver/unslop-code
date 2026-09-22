"""Aggregation of finished rows into the JSON summary printed to stdout."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rows import Result


@dataclass(frozen=True)
class TaskResults:
    """Everything one finished task contributes to the summary."""

    name: str
    results: list[Result]
    api_calls: int


def summarize(tasks: Sequence[TaskResults], elapsed_seconds: float) -> dict[str, Any]:
    """Run totals over every task, plus a per-task breakdown keyed by task name."""
    results = [result for task in tasks for result in task.results]
    metas = [meta for result in results for meta in _metas(result)]
    api_calls = sum(task.api_calls for task in tasks)
    return {
        **_counts(results),
        "total_prompt_tokens": sum(meta["prompt_tokens"] for meta in metas),
        "total_completion_tokens": sum(meta["completion_tokens"] for meta in metas),
        "total_api_calls": api_calls,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "throughput_rpm": round(api_calls / elapsed_seconds * 60, 1) if elapsed_seconds else 0.0,
        "tasks": {task.name: _task_summary(task) for task in tasks},
    }


def _task_summary(task: TaskResults) -> dict[str, Any]:
    """One task's row counts, the solutions its rows produced and the calls it spent."""
    solutions = sum(_solutions(result) for result in task.results)
    return {
        **_counts(task.results),
        "total_solutions": solutions,
        "avg_solutions_per_input": round(solutions / len(task.results), 2) if task.results else 0.0,
        "total_api_calls": task.api_calls,
    }


def _solutions(result: Result) -> int:
    """Solutions a row wrote: the length of a list output, else one per answered row."""
    output = result["output"]
    if isinstance(output, list):
        return len(output)
    return 1 if output is not None else 0


def _counts(results: Sequence[Result]) -> dict[str, int]:
    passed = sum(1 for result in results if _row_passed(result))
    return {"total": len(results), "passed": passed, "failed": len(results) - passed}


def _row_passed(result: Result) -> bool:
    """A row passes on its evaluation, on any kept solution, or — unevaluated — on any answer."""
    passed = result["result"]["passed"]
    if passed is None:
        return result["output"] is not None
    return passed > 0


def _metas(result: Result) -> list[dict[str, Any]]:
    """The per-request metadata of a row, with any judge call it made folded in."""
    meta = result["meta"]
    attempts = meta if isinstance(meta, list) else [meta] if meta else []
    requests = [request for attempt in attempts for request in _requests(attempt)]
    return requests + [attempt["judge_meta"] for attempt in attempts if attempt.get("judge_meta")]


def _requests(attempt: dict[str, Any]) -> list[dict[str, Any]]:
    """The requests one attempt spent: every iteration of an agentic loop, else the attempt itself."""
    return attempt.get("iterations_detail") or [attempt]
