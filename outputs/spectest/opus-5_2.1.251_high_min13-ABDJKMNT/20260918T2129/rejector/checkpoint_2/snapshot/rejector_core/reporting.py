"""Result serialisation: per-row JSONL documents and the run summary."""

from __future__ import annotations

import json
from pathlib import Path

from .api import RunStats
from .config import TaskConfig
from .runner import RowOutcome, TaskRun


def row_document(outcome: RowOutcome, task: TaskConfig) -> dict:
    """Build the JSON object written for one input row."""
    result = {
        "passed": outcome.passed,
        "extracted_answer": outcome.extracted_answer,
        "attempts": outcome.attempts,
    }
    if task.evaluation and task.evaluation.type == "llm_judge":
        result["judge_score"] = outcome.judge_score

    return {
        "input": outcome.row,
        "output": None if outcome.output is None else {task.output_field: outcome.output},
        "result": result,
        "meta": _meta(outcome.metas),
    }


def write_rows(path: str | Path, outcomes: list[RowOutcome], task: TaskConfig) -> None:
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
        "total_prompt_tokens": sum(meta["prompt_tokens"] for meta in metas),
        "total_completion_tokens": sum(meta["completion_tokens"] for meta in metas),
        "total_api_calls": stats.calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.calls / elapsed * 60, 1) if elapsed > 0 else 0.0,
    }
    if per_task:
        summary["tasks"] = {
            run.task.name: {
                **_counts(run.outcomes),
                "total_api_calls": stats.by_task.get(run.task.name, 0),
            }
            for run in runs
        }
    return summary


def _counts(outcomes: list[RowOutcome]) -> dict:
    passed = sum(1 for outcome in outcomes if _is_passed(outcome))
    return {"total": len(outcomes), "passed": passed, "failed": len(outcomes) - passed}


def _meta(metas: list[dict]):
    """A bare object for one-attempt rows, a list for multi-attempt rows."""
    if not metas:
        return None
    return metas[0] if len(metas) == 1 else metas


def _is_passed(outcome: RowOutcome) -> bool:
    """Rows without an evaluation count as passed once a response arrives."""
    return outcome.output is not None and outcome.passed is not False
