"""Result serialisation: per-row JSONL documents and the run summary."""

from __future__ import annotations

import json
from pathlib import Path

from .api import RunStats
from .config import TaskConfig
from .cost import CostTracker
from .runner import RowOutcome, TaskRun, outcome_passed
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
    if outcome.schema_valid is not None:
        result["schema_valid"] = outcome.schema_valid
    if outcome.schema_error is not None:
        result["schema_error"] = outcome.schema_error

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
            {task.output_field: solution.value, "icl_setup": solution.icl_setup}
            for solution in outcome.solutions
        ],
        "result": {
            "passed": outcome.passed,
            "failed": outcome.failed,
            "attempts": outcome.attempts,
        },
        "meta": outcome.metas,
    }


def write_rows(path: str | Path, outcomes: list, task: TaskConfig, append: bool = False) -> None:
    """Write one JSON object per row, in input order.

    A resumed run appends after the rows the previous run already wrote;
    otherwise the file is replaced.
    """
    lines = [json.dumps(row_document(outcome, task)) for outcome in outcomes]
    text = "".join(f"{line}\n" for line in lines)
    with Path(path).open("a" if append else "w") as handle:
        handle.write(text)


def build_summary(
    runs: list[TaskRun],
    stats: RunStats,
    costs: CostTracker,
    per_task: bool,
    resumed: dict | None = None,
) -> dict:
    """Aggregate the run into the summary object printed on stdout.

    `per_task` adds the multi-task `tasks` breakdown; single-task configs
    keep the Part 1 summary shape.  `resumed` maps each task to the rows a
    previous run had already written, and is None outside a resumed run.
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
    if costs.enabled:
        summary["cost"] = costs.summary()
    if resumed is not None:
        summary["resumed_from"] = sum(resumed.values())
    if per_task:
        summary["tasks"] = {
            run.task.name: {
                **_counts(run.outcomes),
                **_solution_counts(run.outcomes),
                "total_api_calls": stats.by_task.get(run.task.name, 0),
                **({"resumed_from": resumed[run.task.name]} if resumed is not None else {}),
            }
            for run in runs
        }
    return summary


def _tokens(meta: dict, kind: str) -> int:
    """One attempt's token count; an agentic loop reports its loop total."""
    return meta.get(kind, meta.get(f"total_{kind}", 0))


def _counts(outcomes: list) -> dict:
    passed = sum(1 for outcome in outcomes if outcome_passed(outcome))
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

