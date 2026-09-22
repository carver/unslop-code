"""Aggregation of finished rows into the JSON summary printed to stdout."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from cost import CostTracker
from rows import Result, row_passed, solution_count


@dataclass(frozen=True)
class TaskResults:
    """Everything one finished task contributes to the summary."""

    name: str
    results: list[Result]
    api_calls: int
    #: Rows `--resume` skipped because an earlier run had already written them.
    resumed_from: int | None = None


def summarize(
    tasks: Sequence[TaskResults], elapsed_seconds: float, cost: CostTracker | None = None
) -> dict[str, Any]:
    """Run totals over every task, plus a per-task breakdown keyed by task name.

    A resumed run counts only the rows it processed itself, and says how many it
    found already done.
    """
    results = [result for task in tasks for result in task.results]
    metas = [meta for result in results for meta in _metas(result)]
    api_calls = sum(task.api_calls for task in tasks)
    return {
        **_counts(results),
        **_resumed(tasks),
        "total_prompt_tokens": sum(meta["prompt_tokens"] for meta in metas),
        "total_completion_tokens": sum(meta["completion_tokens"] for meta in metas),
        "total_api_calls": api_calls,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "throughput_rpm": round(api_calls / elapsed_seconds * 60, 1) if elapsed_seconds else 0.0,
        "tasks": {task.name: _task_summary(task) for task in tasks},
        **_cost(cost),
    }


def _resumed(tasks: Sequence[TaskResults]) -> dict[str, int]:
    """`resumed_from` over every task, for a run that was resumed at all."""
    skipped = [task.resumed_from for task in tasks if task.resumed_from is not None]
    return {"resumed_from": sum(skipped)} if skipped else {}


def _cost(cost: CostTracker | None) -> dict[str, Any]:
    """`cost` for a run that priced its tokens, nothing for one that did not."""
    spend = cost.summary() if cost is not None else None
    return {"cost": spend} if spend is not None else {}


def _task_summary(task: TaskResults) -> dict[str, Any]:
    """One task's row counts, the solutions its rows produced and the calls it spent."""
    solutions = sum(solution_count(result) for result in task.results)
    return {
        **_counts(task.results),
        "total_solutions": solutions,
        "avg_solutions_per_input": round(solutions / len(task.results), 2) if task.results else 0.0,
        "total_api_calls": task.api_calls,
    }


def _counts(results: Sequence[Result]) -> dict[str, int]:
    passed = sum(1 for result in results if row_passed(result))
    return {"total": len(results), "passed": passed, "failed": len(results) - passed}


def _metas(result: Result) -> list[dict[str, Any]]:
    """The per-request metadata of a row, with any judge call it made folded in."""
    meta = result["meta"]
    attempts = meta if isinstance(meta, list) else [meta] if meta else []
    requests = [request for attempt in attempts for request in _requests(attempt)]
    return requests + [attempt["judge_meta"] for attempt in attempts if attempt.get("judge_meta")]


def _requests(attempt: dict[str, Any]) -> list[dict[str, Any]]:
    """The requests one attempt spent: every iteration of an agentic loop, else the attempt itself."""
    return attempt.get("iterations_detail") or [attempt]
