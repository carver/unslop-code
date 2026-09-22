"""Assembling output rows from what each input row produced, and the summary."""

from __future__ import annotations

from dataclasses import dataclass

from rejlib.api import Stats
from rejlib.config import TaskConfig
from rejlib.schemes import Outcome, Try


@dataclass
class TaskRun:
    """One task's output rows, in input order, and the counters it produced."""

    rows: list[dict]
    stats: Stats


def output_row(config: TaskConfig, row: dict, outcome: Outcome) -> dict:
    """One output record; ICL and multi-solution tasks use the list format."""
    if config.list_format:
        return _list_row(config, row, outcome)
    return _single_row(config, row, outcome)


def _single_row(config: TaskConfig, row: dict, outcome: Outcome) -> dict:
    """The Part 1 format: one output object, one verdict, one metadata object."""
    kept = outcome.kept[0] if outcome.kept else None
    verdict = kept.verdict if kept else None
    result = {
        "passed": kept.passed if kept else _failed_without_output(config),
        "extracted_answer": verdict.extracted if verdict else None,
        "attempts": outcome.attempts,
    }
    if config.evaluation and config.evaluation.type == "llm_judge":
        result["judge_score"] = verdict.judge_score if verdict else None  # T28
    return {
        "input": row,
        "output": {config.output_field: kept.content} if kept else None,
        "result": result,
        # A single object for one-attempt rows, a list per attempt otherwise (T14).
        "meta": outcome.metas[0] if outcome.attempts == 1 else outcome.metas,
    }


def _failed_without_output(config: TaskConfig) -> bool | None:
    """A row that produced nothing failed, unless nothing evaluated it (T21)."""
    return None if config.evaluation is None else False


def _list_row(config: TaskConfig, row: dict, outcome: Outcome) -> dict:
    """The multi-solution format: solution list, attempt counts, metadata list."""
    passed = _passing(config, outcome)
    return {
        "input": row,
        "output": [
            {config.output_field: attempt.content, "icl_setup": attempt.setup}
            for attempt in outcome.kept
        ],
        # T38: exactly the three documented counts, one per attempt made.
        "result": {
            "passed": passed,
            "failed": outcome.attempts - passed,
            "attempts": outcome.attempts,
        },
        "meta": [_list_meta(attempt) for attempt in outcome.tries],
    }


def _passing(config: TaskConfig, outcome: Outcome) -> int:
    """Passing solutions, or emitted outputs when nothing evaluates them."""
    if config.evaluation is None:
        return len(outcome.kept)
    return sum(1 for attempt in outcome.tries if attempt.passed)


def _list_meta(attempt: Try) -> dict:
    """Part 1 metadata plus the setup that produced it and its verdict."""
    return {**attempt.meta, "icl_setup": attempt.setup, "evaluation_passed": attempt.passed}


def build_summary(runs: dict[str, TaskRun], multi: bool) -> dict:
    """The one-line JSON summary printed after processing finishes."""
    stats = Stats.merged(run.stats for run in runs.values())
    rows = [row for run in runs.values() for row in run.rows]
    elapsed = stats.elapsed
    summary = {
        **_counts(rows),
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.api_calls / elapsed * 60, 1) if elapsed > 0 else 0.0,
    }
    if multi:
        # T43: only per-task entries report solution counts.
        summary["tasks"] = {
            name: {
                **_counts(run.rows),
                **_solution_counts(run.rows),
                "total_api_calls": run.stats.api_calls,
            }
            for name, run in runs.items()
        }
    return summary


def _counts(rows: list[dict]) -> dict:
    """Row counts over one task's rows, or over every row that ran."""
    passed = sum(1 for row in rows if _counts_as_passed(row))
    return {"total": len(rows), "passed": passed, "failed": len(rows) - passed}


def _counts_as_passed(row: dict) -> bool:
    """A passing evaluation, or - with no evaluation - any produced output.

    A list-format row passes once it holds at least one passing solution (T42).
    """
    passed = row["result"]["passed"]
    if isinstance(row["output"], list):
        return passed > 0
    return passed is True or (passed is None and row["output"] is not None)


def _solution_counts(rows: list[dict]) -> dict:
    """How many solutions a task wrote, in total and per input row."""
    total = sum(_solutions(row) for row in rows)
    return {
        "total_solutions": total,
        "avg_solutions_per_input": round(total / len(rows), 2) if rows else 0.0,
    }


def _solutions(row: dict) -> int:
    output = row["output"]
    if isinstance(output, list):
        return len(output)
    return 0 if output is None else 1
