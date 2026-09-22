"""Shapes outcomes into the JSONL result rows and the stdout summary."""

from __future__ import annotations

import json
from pathlib import Path

from .api import ChatClient
from .config import TaskConfig
from .runner import RowOutcome, TaskResult


def result_row(row: dict, outcome: RowOutcome, task: TaskConfig) -> dict:
    """Build the JSON object written for one input row."""
    result = {
        "passed": outcome.passed,
        "extracted_answer": outcome.extracted_answer,
        "attempts": outcome.attempts,
    }
    if task.judge is not None:
        result["judge_score"] = outcome.judge_score
    return {
        "input": row,
        "output": None if outcome.content is None else {task.output_field: outcome.content},
        "result": result,
        "meta": _meta(outcome.metas),
    }


def _meta(metas: list[dict]) -> dict | list[dict] | None:
    """One object for a single attempt, a list for several, null for none."""
    if not metas:
        return None
    return metas[0] if len(metas) == 1 else metas


def write_results(path: Path, result: TaskResult) -> None:
    """Write one JSON object per input row, in input order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row, outcome in zip(result.rows, result.outcomes):
            handle.write(json.dumps(result_row(row, outcome, result.task)) + "\n")


def build_summary(results: list[TaskResult], client: ChatClient) -> dict:
    """Aggregate the run into the summary object printed to stdout."""
    counts = [_counts(result) for result in results]
    elapsed = round(client.elapsed_seconds, 1)
    # Divide by the reported (rounded) elapsed so the summary is self-consistent,
    # falling back to the raw value for runs too short to round above zero.
    divisor = elapsed or client.elapsed_seconds
    throughput = round(client.usage.calls / divisor * 60, 1) if divisor > 0 else 0.0
    return {
        "total": sum(count["total"] for count in counts),
        "passed": sum(count["passed"] for count in counts),
        "failed": sum(count["failed"] for count in counts),
        "total_prompt_tokens": client.usage.prompt_tokens,
        "total_completion_tokens": client.usage.completion_tokens,
        "total_api_calls": client.usage.calls,
        "elapsed_seconds": elapsed,
        "throughput_rpm": throughput,
        "tasks": {
            result.task.name: count for result, count in zip(results, counts)
        },
    }


def _counts(result: TaskResult) -> dict:
    """One task's row counts, with the API calls charged to it."""
    passed = sum(
        1
        for outcome in result.outcomes
        if outcome.passed is True
        or (outcome.passed is None and outcome.content is not None)
    )
    failed = sum(
        1
        for outcome in result.outcomes
        if outcome.passed is False or outcome.content is None
    )
    return {
        "total": len(result.outcomes),
        "passed": passed,
        "failed": failed,
        "total_api_calls": result.usage.calls,
    }
