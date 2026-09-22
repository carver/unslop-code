"""Shapes outcomes into the JSONL result rows and the stdout summary."""

from __future__ import annotations

import json
from pathlib import Path

from .api import ChatClient
from .config import TaskConfig
from .runner import RowOutcome


def result_row(row: dict, outcome: RowOutcome, output_field: str) -> dict:
    """Build the JSON object written for one input row."""
    return {
        "input": row,
        "output": None if outcome.content is None else {output_field: outcome.content},
        "result": {
            "passed": outcome.passed,
            "extracted_answer": outcome.extracted_answer,
            "attempts": outcome.attempts,
        },
        "meta": _meta(outcome.metas),
    }


def _meta(metas: list[dict]) -> dict | list[dict] | None:
    """One object for a single attempt, a list for several, null for none."""
    if not metas:
        return None
    return metas[0] if len(metas) == 1 else metas


def write_results(
    path: Path, rows: list[dict], outcomes: list[RowOutcome], config: TaskConfig
) -> None:
    """Write one JSON object per input row, in input order."""
    with path.open("w") as handle:
        for row, outcome in zip(rows, outcomes):
            handle.write(json.dumps(result_row(row, outcome, config.output_field)) + "\n")


def build_summary(outcomes: list[RowOutcome], client: ChatClient) -> dict:
    """Aggregate the run into the summary object printed to stdout."""
    passed = sum(
        1
        for outcome in outcomes
        if outcome.passed is True
        or (outcome.passed is None and outcome.content is not None)
    )
    failed = sum(
        1 for outcome in outcomes if outcome.passed is False or outcome.content is None
    )
    elapsed = round(client.elapsed_seconds, 1)
    # Divide by the reported (rounded) elapsed so the summary is self-consistent,
    # falling back to the raw value for runs too short to round above zero.
    divisor = elapsed or client.elapsed_seconds
    throughput = round(client.total_calls / divisor * 60, 1) if divisor > 0 else 0.0
    return {
        "total": len(outcomes),
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": client.total_prompt_tokens,
        "total_completion_tokens": client.total_completion_tokens,
        "total_api_calls": client.total_calls,
        "elapsed_seconds": elapsed,
        "throughput_rpm": throughput,
    }
