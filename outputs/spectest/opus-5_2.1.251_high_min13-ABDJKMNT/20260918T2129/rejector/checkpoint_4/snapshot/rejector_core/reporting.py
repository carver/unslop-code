"""Result serialisation: per-row JSONL documents and the run summary."""

from __future__ import annotations

import json
from pathlib import Path

from .api import RunStats
from .config import TaskConfig
from .runner import RowOutcome, TaskRun
from .solutions import MultiOutcome


def row_document(outcome: RowOutcome | MultiOutcome, task: TaskConfig) -> dict:
    """Build the JSON object written for one input row."""
    if isinstance(outcome, MultiOutcome):
        return _solutions_document(outcome, task)

    result = {
        "passed": outcome.passed,
        "extracted_answer": outcome.extracted_answer,
        "attempts": outcome.attempts,
    }
    if outcome.loop is not None:
        result["iterations"] = outcome.loop.iterations
        result["tool_calls"] = outcome.loop.tool_calls
    if task.evaluation and task.evaluation.type == "llm_judge":
        result["judge_score"] = outcome.judge_score

    return {
        "input": outcome.row,
        "output": None if outcome.output is None else {task.output_field: outcome.output},
        "result": result,
        "meta": _meta(outcome.metas),
    }


def _solutions_document(outcome: MultiOutcome, task: TaskConfig) -> dict:
    """The multi-solution row format: a list of outputs and a list of metadata."""
    return {
        "input": outcome.row,
        "output": [
            {task.output_field: solution.text, "icl_setup": solution.icl_setup}
            for solution in outcome.solutions
        ],
        "result": {
            "passed": outcome.passed,
            "failed": outcome.failed,
            "attempts": outcome.attempts,
        },
        "meta": outcome.metas,
    }


def write_rows(path: str | Path, outcomes: list, task: TaskConfig) -> None:
    """Write one JSON object per row, in input order, overwriting the file."""
    lines = [json.dumps(row_document(outcome, task)) for outcome in outcomes]
    Path(path).write_text("".join(f"{line}\n" for line in lines))


def build_summary(runs: list[TaskRun], stats: RunStats, per_task: bool) -> dict:
    """Aggregate the run into the summary object printed on stdout.

    `per_task` adds the multi-task `tasks` breakdown; single-task configs
    keep the Part 1 summary shape.
    """
    outcomes = [outcome for run in runs for outcome in run.outcomes]
    metas = [meta for outcome in outcomes for meta in outcome.metas]
    elapsed = stats.elapsed_seconds

    summary = {
        **_counts(outcomes),
        "total_prompt_tokens": sum(_tokens(meta, "prompt_tokens") for meta in metas),
        "total_completion_tokens": sum(_tokens(meta, "completion_tokens") for meta in metas),
        "total_api_calls": stats.calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.calls / elapsed * 60, 1) if elapsed > 0 else 0.0,
    }
    if per_task:
        summary["tasks"] = {
            run.task.name: {
                **_counts(run.outcomes),
                **_solution_counts(run.outcomes),
                "total_api_calls": stats.by_task.get(run.task.name, 0),
            }
            for run in runs
        }
    return summary


def _tokens(meta: dict, kind: str) -> int:
    """One attempt's token count; an agentic loop reports its loop total."""
    return meta.get(kind, meta.get(f"total_{kind}", 0))


def _counts(outcomes: list) -> dict:
    passed = sum(1 for outcome in outcomes if _is_passed(outcome))
    return {"total": len(outcomes), "passed": passed, "failed": len(outcomes) - passed}


def _solution_counts(outcomes: list) -> dict:
    """How many solutions a task wrote, in total and per input row."""
    total = sum(_solutions_written(outcome) for outcome in outcomes)
    return {
        "total_solutions": total,
        "avg_solutions_per_input": round(total / len(outcomes), 2) if outcomes else 0.0,
    }


def _solutions_written(outcome: RowOutcome | MultiOutcome) -> int:
    if isinstance(outcome, MultiOutcome):
        return len(outcome.solutions)
    return 0 if outcome.output is None else 1


def _meta(metas: list[dict]):
    """A bare object for one-attempt rows, a list for multi-attempt rows."""
    if not metas:
        return None
    return metas[0] if len(metas) == 1 else metas


def _is_passed(outcome: RowOutcome | MultiOutcome) -> bool:
    """A row passes once it holds a response that evaluation did not reject.

    In the multi-solution format that means at least one passing solution;
    without an evaluation every emitted solution counts as passing.
    """
    if isinstance(outcome, MultiOutcome):
        return outcome.passed > 0
    return outcome.output is not None and outcome.passed is not False
