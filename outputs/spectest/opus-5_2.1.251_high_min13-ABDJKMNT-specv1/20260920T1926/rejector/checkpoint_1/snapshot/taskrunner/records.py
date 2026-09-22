"""Shaping outcomes into JSONL rows and the run summary."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .config import TaskConfig
from .generation import RowOutcome


def build_record(
    row: Mapping[str, Any], outcome: RowOutcome, config: TaskConfig
) -> dict[str, Any]:
    """The output object for one input row."""
    output = None if outcome.text is None else {config.output_field: outcome.text}
    return {
        "input": dict(row),
        "output": output,
        "result": {
            "passed": outcome.passed,
            "extracted_answer": outcome.extracted,
            "attempts": outcome.attempts,
        },
        "meta": _meta(outcome),
    }


def _meta(outcome: RowOutcome) -> Any:
    """One object for a single-attempt row, a list once attempts pile up."""
    metas = [meta.as_dict() for meta in outcome.metas]
    if not metas:
        return None
    return metas[0] if len(metas) == 1 else metas


def build_summary(outcomes: Sequence[RowOutcome], elapsed: float) -> dict[str, Any]:
    """Aggregate counters printed to stdout when the run finishes."""
    metas = [meta for outcome in outcomes for meta in outcome.metas]
    api_calls = sum(outcome.api_calls for outcome in outcomes)
    return {
        "total": len(outcomes),
        "passed": sum(1 for outcome in outcomes if _counts_as_passed(outcome)),
        "failed": sum(1 for outcome in outcomes if _counts_as_failed(outcome)),
        "total_prompt_tokens": sum(meta.prompt_tokens for meta in metas),
        "total_completion_tokens": sum(meta.completion_tokens for meta in metas),
        "total_api_calls": api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(api_calls / elapsed * 60, 1) if elapsed else 0.0,
    }


def _counts_as_passed(outcome: RowOutcome) -> bool:
    """Without an evaluation, any row that got a response counts as passed."""
    return outcome.passed is True or (outcome.passed is None and outcome.text is not None)


def _counts_as_failed(outcome: RowOutcome) -> bool:
    return outcome.passed is False or outcome.text is None
