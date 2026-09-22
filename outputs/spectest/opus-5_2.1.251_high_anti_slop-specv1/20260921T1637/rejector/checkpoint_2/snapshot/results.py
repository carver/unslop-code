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
class Attempt:
    """One logical generation attempt: its API call, plus the judge call it triggered."""

    meta: CallMeta
    judge_meta: CallMeta | None = None

    def to_json(self) -> dict[str, Any]:
        payload = self.meta.to_json()
        if self.judge_meta is not None:
            payload["judge_meta"] = self.judge_meta.to_json()
        return payload


@dataclass(frozen=True)
class RowOutcome:
    """Everything produced for one input row, with one ``Attempt`` per logical attempt."""

    row: dict[str, Any]
    text: str | None
    passed: bool | None
    extracted_answer: str | None
    judge_score: float | int | None
    attempts: list[Attempt]

    @property
    def succeeded(self) -> bool:
        """True when the row produced output that did not fail its evaluation."""
        return self.text is not None and self.passed is not False

    @property
    def judged(self) -> bool:
        """True when a judge scored at least one of this row's attempts."""
        return any(attempt.judge_meta is not None for attempt in self.attempts)


def write_results(path: str, outcomes: list[RowOutcome], output_field: str) -> None:
    """Write one JSON object per outcome to ``path``, in input order."""
    with open(path, "w", encoding="utf-8") as handle:
        for outcome in outcomes:
            handle.write(json.dumps(_row_json(outcome, output_field)) + "\n")


def build_summary(outcomes: list[RowOutcome], api_calls: int, elapsed_seconds: float) -> dict[str, Any]:
    """Aggregate the whole run into the summary object printed to stdout."""
    metas = [attempt.meta for outcome in outcomes for attempt in outcome.attempts]
    throughput = api_calls / elapsed_seconds * 60 if elapsed_seconds > 0 else 0.0
    return {
        **_counts(outcomes),
        "total_prompt_tokens": sum(meta.prompt_tokens for meta in metas),
        "total_completion_tokens": sum(meta.completion_tokens for meta in metas),
        "total_api_calls": api_calls,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "throughput_rpm": round(throughput, 1),
    }


def task_totals(outcomes: list[RowOutcome], api_calls: int) -> dict[str, Any]:
    """One task's entry in the summary's ``tasks`` object."""
    return {**_counts(outcomes), "total_api_calls": api_calls}


def _counts(outcomes: list[RowOutcome]) -> dict[str, int]:
    passed = sum(1 for outcome in outcomes if outcome.succeeded)
    return {"total": len(outcomes), "passed": passed, "failed": len(outcomes) - passed}


def _row_json(outcome: RowOutcome, output_field: str) -> dict[str, Any]:
    result = {
        "passed": outcome.passed,
        "extracted_answer": outcome.extracted_answer,
        "attempts": len(outcome.attempts),
    }
    if outcome.judged:
        result["judge_score"] = outcome.judge_score
    metas = [attempt.to_json() for attempt in outcome.attempts]
    return {
        "input": outcome.row,
        "output": None if outcome.text is None else {output_field: outcome.text},
        "result": result,
        "meta": metas[0] if len(metas) == 1 else metas,
    }
