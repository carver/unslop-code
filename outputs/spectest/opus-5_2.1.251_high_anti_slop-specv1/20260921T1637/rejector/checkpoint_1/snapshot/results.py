"""Result records, their JSONL serialization, and the run summary."""

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CallMeta:
    """Metadata for one API call, emitted in the output ``meta`` field."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    finish_reason: str | None
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Serialize the call, adding ``error`` only when the call never returned a response."""
        payload = {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
        }
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass(frozen=True)
class RowOutcome:
    """Everything produced for one input row, with one ``CallMeta`` per logical attempt."""

    row: dict[str, Any]
    text: str | None
    passed: bool | None
    extracted_answer: str | None
    metas: list[CallMeta]

    @property
    def attempts(self) -> int:
        """Logical generation attempts; HTTP retries of one attempt do not count."""
        return len(self.metas)

    @property
    def succeeded(self) -> bool:
        """True when the row produced output that did not fail its evaluation."""
        return self.text is not None and self.passed is not False


def write_results(path: str, outcomes: list[RowOutcome], output_field: str) -> None:
    """Write one JSON object per outcome to ``path``, in input order."""
    with open(path, "w", encoding="utf-8") as handle:
        for outcome in outcomes:
            handle.write(json.dumps(_row_json(outcome, output_field)) + "\n")


def build_summary(outcomes: list[RowOutcome], api_calls: int, elapsed_seconds: float) -> dict[str, Any]:
    """Aggregate the run into the summary object printed to stdout."""
    metas = [meta for outcome in outcomes for meta in outcome.metas]
    throughput = api_calls / elapsed_seconds * 60 if elapsed_seconds > 0 else 0.0
    return {
        "total": len(outcomes),
        "passed": sum(1 for outcome in outcomes if outcome.succeeded),
        "failed": sum(1 for outcome in outcomes if not outcome.succeeded),
        "total_prompt_tokens": sum(meta.prompt_tokens for meta in metas),
        "total_completion_tokens": sum(meta.completion_tokens for meta in metas),
        "total_api_calls": api_calls,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "throughput_rpm": round(throughput, 1),
    }


def _row_json(outcome: RowOutcome, output_field: str) -> dict[str, Any]:
    metas = [meta.to_json() for meta in outcome.metas]
    return {
        "input": outcome.row,
        "output": None if outcome.text is None else {output_field: outcome.text},
        "result": {
            "passed": outcome.passed,
            "extracted_answer": outcome.extracted_answer,
            "attempts": outcome.attempts,
        },
        "meta": metas[0] if len(metas) == 1 else metas,
    }
