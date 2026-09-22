"""Shaping what a run produced into output records and the run summary.

A task keeping the Part 1 result shape writes one output object per row; a task
with ICL or several solutions writes a list of them, with one metadata entry per
attempt rather than per kept response.
"""

from __future__ import annotations

from config import TaskConfig
from evaluation import Verdict
from schemes import AttemptOutcome, RowOutcome


def record(config: TaskConfig, row: dict, outcome: RowOutcome) -> dict:
    """One output line for one input row."""
    if config.legacy:
        return _single_record(config, row, outcome)
    return _list_record(config, row, outcome)


def _single_record(config: TaskConfig, row: dict, outcome: RowOutcome) -> dict:
    """The Part 1 shape: metadata stays a bare object unless several attempts were made."""
    # A row that kept nothing has no verdict of its own: the attempts it made all failed.
    verdict = outcome.solutions[0].verdict if outcome.solutions else Verdict(False, None)
    result = {
        "passed": verdict.passed,
        "extracted_answer": verdict.extracted,
        "attempts": len(outcome.attempts),
    }
    if config.evaluation is not None and config.evaluation.type == "llm_judge":
        result["judge_score"] = verdict.judge_score

    metas = [attempt.meta for attempt in outcome.attempts]
    return {
        "input": row,
        "output": {config.output_field: outcome.solutions[0].text} if outcome.solutions else None,
        "result": result,
        "meta": metas[0] if len(metas) == 1 else metas,
    }


def _list_record(config: TaskConfig, row: dict, outcome: RowOutcome) -> dict:
    """The multiple solution shape: every kept response and every attempt it took."""
    attempts = len(outcome.attempts)
    return {
        "input": row,
        "output": [
            {config.output_field: solution.text, "icl_setup": solution.setup}
            for solution in outcome.solutions
        ],
        "result": {
            "passed": outcome.passed,
            "failed": attempts - outcome.passed,
            "attempts": attempts,
        },
        "meta": [_meta_entry(attempt) for attempt in outcome.attempts],
    }


def _meta_entry(attempt: AttemptOutcome) -> dict | None:
    """One attempt's metadata, tagged with its setup and verdict."""
    if attempt.meta is None:
        return None
    return {
        **attempt.meta,
        "icl_setup": attempt.setup,
        "evaluation_passed": attempt.verdict.passed,
    }


def summarize(results: dict, elapsed: float, per_task: bool) -> dict:
    """Build the JSON summary printed once a run finishes.

    `results` maps task names to their `runner.TaskResult`.
    """
    records = [record for result in results.values() for record in result.records]
    metas = _metas(records)
    api_calls = sum(result.api_calls for result in results.values())

    summary = {
        **_counts(records),
        "total_prompt_tokens": sum(meta["prompt_tokens"] for meta in metas),
        "total_completion_tokens": sum(meta["completion_tokens"] for meta in metas),
        "total_api_calls": api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(api_calls / elapsed * 60, 1) if elapsed else 0.0,
    }
    if per_task:
        summary["tasks"] = {
            name: {
                **_counts(result.records),
                **_solution_counts(result.records),
                "total_api_calls": result.api_calls,
            }
            for name, result in results.items()
        }
    return summary


def _counts(records: list[dict]) -> dict:
    """Row totals. Without an evaluation a row passes as long as the API answered it."""
    passed = sum(
        1
        for record in records
        if record["result"]["passed"]
        or (record["result"]["passed"] is None and record["output"] is not None)
    )
    return {"total": len(records), "passed": passed, "failed": len(records) - passed}


def _solution_counts(records: list[dict]) -> dict:
    """How many responses a task wrote out, in total and per input row."""
    total = sum(_solutions(record) for record in records)
    return {
        "total_solutions": total,
        "avg_solutions_per_input": round(total / len(records), 2) if records else 0.0,
    }


def _solutions(record: dict) -> int:
    output = record["output"]
    if isinstance(output, list):
        return len(output)
    return 0 if output is None else 1


def _metas(records: list[dict]) -> list[dict]:
    """Every API call's metadata, judge calls included."""
    metas = []
    for record in records:
        entries = record["meta"] if isinstance(record["meta"], list) else [record["meta"]]
        for meta in entries:
            if meta is None:
                continue
            metas.append(meta)
            if meta.get("judge_meta") is not None:
                metas.append(meta["judge_meta"])
    return metas
