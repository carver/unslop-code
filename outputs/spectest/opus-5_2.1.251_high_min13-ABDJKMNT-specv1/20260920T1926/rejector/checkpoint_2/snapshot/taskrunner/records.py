"""Shaping outcomes into JSONL rows and the run summary."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .config import TaskConfig
from .generation import RowOutcome


def build_record(
    row: Mapping[str, Any], outcome: RowOutcome, config: TaskConfig
) -> dict[str, Any]:
    """The output object for one input row."""
    result = {
        "passed": outcome.passed,
        "extracted_answer": outcome.extracted,
        "attempts": outcome.attempts,
    }
    if config.evaluation and config.evaluation.judge:
        result["judge_score"] = outcome.judge_score
    return {
        "input": dict(row),
        "output": None if outcome.text is None else {config.output_field: outcome.text},
        "result": result,
        "meta": _meta(outcome),
    }


def _meta(outcome: RowOutcome) -> Any:
    """One object for a single-attempt row, a list once attempts pile up.

    Each attempt carries the judge call that scored it, when there was one.
    """
    entries = []
    for meta, judge_meta in zip(outcome.metas, outcome.judge_metas):
        entry = meta.as_dict()
        if judge_meta is not None:
            entry["judge_meta"] = judge_meta.as_dict()
        entries.append(entry)
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
        summary["tasks"] = {
            name: {**_counters(task), "total_api_calls": sum(o.api_calls for o in task)}
            for name, task in results.items()
        }
    return summary


def _counters(outcomes: Sequence[RowOutcome]) -> dict[str, int]:
    return {
        "total": len(outcomes),
        "passed": sum(1 for outcome in outcomes if _counts_as_passed(outcome)),
        "failed": sum(1 for outcome in outcomes if _counts_as_failed(outcome)),
    }


def _all_metas(outcome: RowOutcome) -> list[Any]:
    """Generation and judge metadata alike; both are API calls of the run."""
    judged = [meta for meta in outcome.judge_metas if meta is not None]
    return outcome.metas + judged


def _counts_as_passed(outcome: RowOutcome) -> bool:
    """Without an evaluation, any row that got a response counts as passed."""
    return outcome.passed is True or (outcome.passed is None and outcome.text is not None)


def _counts_as_failed(outcome: RowOutcome) -> bool:
    return outcome.passed is False or outcome.text is None
