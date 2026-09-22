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
    """One logical generation attempt: its API call, plus the judge call it triggered.

    ``icl_setup`` and ``evaluation_passed`` are reported only by the multi-solution
    output format; both are ``None`` when there was no ICL setup or no evaluation.
    """

    meta: CallMeta
    judge_meta: CallMeta | None = None
    icl_setup: str | None = None
    evaluation_passed: bool | None = None

    def to_json(self) -> dict[str, Any]:
        payload = self.meta.to_json()
        if self.judge_meta is not None:
            payload["judge_meta"] = self.judge_meta.to_json()
        return payload

    def to_detailed_json(self) -> dict[str, Any]:
        """The attempt as the multi-solution format writes it, naming its setup and verdict."""
        return {**self.to_json(), "icl_setup": self.icl_setup, "evaluation_passed": self.evaluation_passed}


@dataclass(frozen=True)
class Solution:
    """One kept response and the ICL setup that produced it."""

    text: str
    icl_setup: str | None


@dataclass(frozen=True)
class ToolInvocation:
    """One tool call an agentic loop made, and what the handler answered."""

    iteration: int
    tool: str
    args: dict[str, Any]
    result: str

    def to_json(self) -> dict[str, Any]:
        return {"iteration": self.iteration, "tool": self.tool, "args": self.args, "result": self.result}


@dataclass(frozen=True)
class AgenticRun:
    """One agentic loop: its final text, the tools it called, and the calls it made.

    ``text`` is ``None`` when the loop ran out of iterations. ``icl_setup`` and
    ``evaluation_passed`` are reported only by the multi-solution output format.
    """

    text: str | None
    tool_calls: list[ToolInvocation]
    metas: list[CallMeta]
    latency_ms: int
    finish_reason: str | None
    icl_setup: str | None = None
    evaluation_passed: bool | None = None

    @property
    def iterations(self) -> int:
        """API requests the loop spent, one per iteration."""
        return len(self.metas)

    def to_json(self) -> dict[str, Any]:
        """The loop's metadata: totals across its iterations, then each one in turn."""
        return {
            "total_prompt_tokens": sum(meta.prompt_tokens for meta in self.metas),
            "total_completion_tokens": sum(meta.completion_tokens for meta in self.metas),
            "total_tokens": sum(meta.total_tokens for meta in self.metas),
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "iterations_detail": [_iteration_detail(meta) for meta in self.metas],
        }

    def to_detailed_json(self) -> dict[str, Any]:
        """The loop as the multi-solution format writes it, naming its setup and verdict."""
        return {**self.to_json(), "icl_setup": self.icl_setup, "evaluation_passed": self.evaluation_passed}


def _iteration_detail(meta: CallMeta) -> dict[str, Any]:
    """One iteration's usage, latency, and finish reason; the model is the run's throughout."""
    detail = meta.to_json()
    detail.pop("model")
    return detail


@dataclass(frozen=True)
class RowOutcome:
    """One input row's single response, in the Part 1 output format."""

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
    def solution_count(self) -> int:
        return 1 if self.text is not None else 0

    @property
    def call_metas(self) -> list[CallMeta]:
        return [attempt.meta for attempt in self.attempts]

    def to_json(self, output_field: str) -> dict[str, Any]:
        result = {
            "passed": self.passed,
            "extracted_answer": self.extracted_answer,
            "attempts": len(self.attempts),
        }
        if any(attempt.judge_meta is not None for attempt in self.attempts):
            result["judge_score"] = self.judge_score
        metas = [attempt.to_json() for attempt in self.attempts]
        return {
            "input": self.row,
            "output": None if self.text is None else {output_field: self.text},
            "result": result,
            "meta": metas[0] if len(metas) == 1 else metas,
        }


@dataclass(frozen=True)
class MultiOutcome:
    """One input row's collected solutions, in the ICL / multi-solution output format.

    ``graded`` records whether an evaluation ran, which decides whether a
    solution counts as passing or merely as emitted.
    """

    row: dict[str, Any]
    solutions: list[Solution]
    attempts: list[Attempt]
    graded: bool

    @property
    def succeeded(self) -> bool:
        """True when the row produced a solution that did not fail its evaluation."""
        return self.passed_count > 0

    @property
    def solution_count(self) -> int:
        return len(self.solutions)

    @property
    def passed_count(self) -> int:
        """Attempts that passed evaluation, or emitted solutions when nothing was evaluated."""
        if not self.graded:
            return len(self.solutions)
        return sum(1 for attempt in self.attempts if attempt.evaluation_passed)

    @property
    def call_metas(self) -> list[CallMeta]:
        return [attempt.meta for attempt in self.attempts]

    def to_json(self, output_field: str) -> dict[str, Any]:
        return {
            "input": self.row,
            "output": [
                {output_field: solution.text, "icl_setup": solution.icl_setup}
                for solution in self.solutions
            ],
            "result": {
                "passed": self.passed_count,
                "failed": len(self.attempts) - self.passed_count,
                "attempts": len(self.attempts),
            },
            "meta": [attempt.to_detailed_json() for attempt in self.attempts],
        }


@dataclass(frozen=True)
class AgenticOutcome:
    """One input row's agentic loop, in the single-solution output format."""

    row: dict[str, Any]
    run: AgenticRun
    passed: bool | None
    extracted_answer: str | None
    judge_score: float | int | None = None
    judged: bool = False

    @property
    def succeeded(self) -> bool:
        """True when the loop answered and that answer did not fail its evaluation."""
        return self.run.text is not None and self.passed is not False

    @property
    def solution_count(self) -> int:
        return 1 if self.run.text is not None else 0

    @property
    def call_metas(self) -> list[CallMeta]:
        return self.run.metas

    def to_json(self, output_field: str) -> dict[str, Any]:
        result = {
            "passed": self.passed,
            "extracted_answer": self.extracted_answer,
            "attempts": 1,
            "iterations": self.run.iterations,
            "tool_calls": [call.to_json() for call in self.run.tool_calls],
        }
        if self.judged:
            result["judge_score"] = self.judge_score
        return {
            "input": self.row,
            "output": None if self.run.text is None else {output_field: self.run.text},
            "result": result,
            "meta": self.run.to_json(),
        }


@dataclass(frozen=True)
class MultiAgenticOutcome:
    """One input row's agentic loops, in the ICL / multi-solution output format.

    Each loop contributes one output entry and one metadata entry, so
    ``result.attempts`` counts loops rather than the API requests they spent.
    """

    row: dict[str, Any]
    runs: list[AgenticRun]
    graded: bool

    @property
    def succeeded(self) -> bool:
        return self.passed_count > 0

    @property
    def solution_count(self) -> int:
        return len(self._answered)

    @property
    def passed_count(self) -> int:
        """Loops that passed evaluation, or loops that answered when nothing was evaluated."""
        if not self.graded:
            return len(self._answered)
        return sum(1 for run in self.runs if run.evaluation_passed)

    @property
    def call_metas(self) -> list[CallMeta]:
        return [meta for run in self.runs for meta in run.metas]

    @property
    def _answered(self) -> list[AgenticRun]:
        return [run for run in self.runs if run.text is not None]

    def to_json(self, output_field: str) -> dict[str, Any]:
        return {
            "input": self.row,
            "output": [
                {output_field: run.text, "icl_setup": run.icl_setup} for run in self._answered
            ],
            "result": {
                "passed": self.passed_count,
                "failed": len(self.runs) - self.passed_count,
                "attempts": len(self.runs),
            },
            "meta": [run.to_detailed_json() for run in self.runs],
        }


#: A row's result in whichever of the output formats its task uses.
Outcome = RowOutcome | MultiOutcome | AgenticOutcome | MultiAgenticOutcome


def write_results(path: str, outcomes: list[Outcome], output_field: str) -> None:
    """Write one JSON object per outcome to ``path``, in input order."""
    with open(path, "w", encoding="utf-8") as handle:
        for outcome in outcomes:
            handle.write(json.dumps(outcome.to_json(output_field)) + "\n")


def build_summary(outcomes: list[Outcome], api_calls: int, elapsed_seconds: float) -> dict[str, Any]:
    """Aggregate the whole run into the summary object printed to stdout."""
    metas = [meta for outcome in outcomes for meta in outcome.call_metas]
    throughput = api_calls / elapsed_seconds * 60 if elapsed_seconds > 0 else 0.0
    return {
        **_counts(outcomes),
        "total_prompt_tokens": sum(meta.prompt_tokens for meta in metas),
        "total_completion_tokens": sum(meta.completion_tokens for meta in metas),
        "total_api_calls": api_calls,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "throughput_rpm": round(throughput, 1),
    }


def task_totals(outcomes: list[Outcome], api_calls: int) -> dict[str, Any]:
    """One task's entry in the summary's ``tasks`` object."""
    solutions = sum(outcome.solution_count for outcome in outcomes)
    average = solutions / len(outcomes) if outcomes else 0.0
    return {
        **_counts(outcomes),
        "total_solutions": solutions,
        "avg_solutions_per_input": round(average, 2),
        "total_api_calls": api_calls,
    }


def _counts(outcomes: list[Outcome]) -> dict[str, int]:
    passed = sum(1 for outcome in outcomes if outcome.succeeded)
    return {"total": len(outcomes), "passed": passed, "failed": len(outcomes) - passed}
