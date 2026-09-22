"""Concurrent execution of the selected tasks over their input rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from client import ChatClient, ClientStats, combine_stats, open_clients
from config import TaskConfig
from dataset import RenderedPrompt
from jobs import TaskJob
from verdicts import Verdict, evaluate_response


@dataclass(frozen=True)
class Attempt:
    """One generated response, with the metadata and verdict it produced."""

    text: str
    meta: dict[str, Any]
    verdict: Verdict


@dataclass(frozen=True)
class RowOutcome:
    """What a single input row produced, before it is shaped into a record."""

    output: str | None
    verdict: Verdict
    attempts: int
    metas: list[dict[str, Any]]


@dataclass(frozen=True)
class TaskResult:
    """One task's records in input order, with the counters its calls ran up."""

    name: str
    records: list[dict[str, Any]]
    stats: ClientStats


async def run_tasks(jobs: list[TaskJob]) -> list[TaskResult]:
    """Process every task concurrently and return their results in job order.

    Rows within a task, and the tasks themselves, are all in flight at once;
    each task's requests are paced by its own `rpm`, so the work of different
    tasks interleaves freely.
    """
    async with open_clients([job.config for job in jobs]) as clients:
        records = await asyncio.gather(
            *(_run_job(client, job) for client, job in zip(clients, jobs))
        )
    return [
        TaskResult(job.config.name, job_records, client.stats)
        for job, job_records, client in zip(jobs, records, clients)
    ]


async def _run_job(client: ChatClient, job: TaskJob) -> list[dict[str, Any]]:
    outcomes = await asyncio.gather(
        *(_run_row(client, job.config, prompt, row) for prompt, row in zip(job.prompts, job.rows))
    )
    return [_to_record(job.config, row, outcome) for row, outcome in zip(job.rows, outcomes)]


async def _run_row(
    client: ChatClient, config: TaskConfig, prompt: RenderedPrompt, row: dict[str, Any]
) -> RowOutcome:
    if config.generation.scheme == "rejection":
        return await _run_rejection(client, config, prompt, row)

    attempt = await _attempt(client, config, prompt, row)
    if attempt is None:
        return _failed_outcome(config, attempts=1, metas=[])
    return RowOutcome(attempt.text, attempt.verdict, 1, [attempt.meta])


async def _run_rejection(
    client: ChatClient, config: TaskConfig, prompt: RenderedPrompt, row: dict[str, Any]
) -> RowOutcome:
    """Sample until a response passes the evaluation or the budget runs out."""
    metas: list[dict[str, Any]] = []
    for number in range(1, config.generation.n + 1):
        attempt = await _attempt(client, config, prompt, row)
        if attempt is None:
            continue
        metas.append(attempt.meta)
        if attempt.verdict.passed:
            return RowOutcome(attempt.text, attempt.verdict, number, metas)
    return _failed_outcome(config, attempts=config.generation.n, metas=metas)


async def _attempt(
    client: ChatClient, config: TaskConfig, prompt: RenderedPrompt, row: dict[str, Any]
) -> Attempt | None:
    """Generate one response and judge it, or return None if the API never answered."""
    generation = config.generation
    completion = await client.complete(prompt, generation.temperature, generation.max_tokens)
    if completion is None:
        return None
    verdict = await evaluate_response(config.evaluation, completion.text, row, client)
    meta = completion.meta
    if verdict.judge_meta is not None:
        meta = {**meta, "judge_meta": verdict.judge_meta}
    return Attempt(completion.text, meta, verdict)


def _failed_outcome(config: TaskConfig, attempts: int, metas: list[dict[str, Any]]) -> RowOutcome:
    """A row with no usable output; `passed` stays None when nothing judges it."""
    return RowOutcome(None, Verdict(passed=False if config.evaluation else None), attempts, metas)


def _to_record(config: TaskConfig, row: dict[str, Any], outcome: RowOutcome) -> dict[str, Any]:
    # One metadata object for single-attempt rows, a list once rejection sampling
    # made several attempts, and null when no attempt reached the API.
    metas = outcome.metas
    result = {
        "passed": outcome.verdict.passed,
        "extracted_answer": outcome.verdict.extracted_answer,
        "attempts": outcome.attempts,
    }
    if config.evaluation and config.evaluation.type == "llm_judge":
        result["judge_score"] = outcome.verdict.judge_score
    return {
        "input": row,
        "output": None if outcome.output is None else {config.output_field: outcome.output},
        "result": result,
        "meta": metas[0] if len(metas) == 1 else (metas or None),
    }


def summarize(results: list[TaskResult], multi: bool) -> dict[str, Any]:
    """Build the run summary printed to stdout.

    Rows with no evaluation configured count as passed as long as the API
    answered them. A multi-task run also reports the same counts per task,
    including the API calls its judge made.
    """
    stats = combine_stats([result.stats for result in results])
    elapsed = stats.elapsed_seconds
    summary = {
        **_counts([record for result in results for record in result.records]),
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.api_calls / elapsed * 60, 1) if elapsed else 0.0,
    }
    if multi:
        summary["tasks"] = {
            result.name: {**_counts(result.records), "total_api_calls": result.stats.api_calls}
            for result in results
        }
    return summary


def _counts(records: list[dict[str, Any]]) -> dict[str, int]:
    passed = sum(1 for record in records if _is_passed(record))
    return {"total": len(records), "passed": passed, "failed": len(records) - passed}


def _is_passed(record: dict[str, Any]) -> bool:
    passed = record["result"]["passed"]
    return passed is True or (passed is None and record["output"] is not None)
