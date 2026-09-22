"""Result serialisation: per-row JSONL documents and the run summary."""

from __future__ import annotations

import json
from pathlib import Path

from .api import ApiStats
from .runner import RowOutcome


def row_document(outcome: RowOutcome, output_field: str) -> dict:
    """Build the JSON object written for one input row."""
    return {
        "input": outcome.row,
        "output": None if outcome.output is None else {output_field: outcome.output},
        "result": {
            "passed": outcome.passed,
            "extracted_answer": outcome.extracted_answer,
            "attempts": outcome.attempts,
        },
        "meta": _meta(outcome.metas),
    }


def write_rows(path: str | Path, outcomes: list[RowOutcome], output_field: str) -> None:
    """Write one JSON object per row, in input order, overwriting the file."""
    lines = [json.dumps(row_document(outcome, output_field)) for outcome in outcomes]
    Path(path).write_text("".join(f"{line}\n" for line in lines))


def build_summary(outcomes: list[RowOutcome], stats: ApiStats) -> dict:
    """Aggregate the run into the summary object printed on stdout."""
    metas = [meta for outcome in outcomes for meta in outcome.metas]
    elapsed = stats.elapsed_seconds
    return {
        "total": len(outcomes),
        "passed": sum(1 for outcome in outcomes if _is_passed(outcome)),
        "failed": sum(1 for outcome in outcomes if not _is_passed(outcome)),
        "total_prompt_tokens": sum(meta["prompt_tokens"] for meta in metas),
        "total_completion_tokens": sum(meta["completion_tokens"] for meta in metas),
        "total_api_calls": stats.calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.calls / elapsed * 60, 1) if elapsed > 0 else 0.0,
    }


def _meta(metas: list[dict]):
    """A bare object for one-attempt rows, a list for multi-attempt rows."""
    if not metas:
        return None
    return metas[0] if len(metas) == 1 else metas


def _is_passed(outcome: RowOutcome) -> bool:
    """Rows without an evaluation count as passed once a response arrives."""
    return outcome.output is not None and outcome.passed is not False
