"""Concurrent execution of the planned tasks."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterator

import aiohttp

from client import Attempt, ChatClient, RateLimiter
from config import TaskConfig
from evaluation import Verdict, evaluate
from jobs import Job


@dataclass(frozen=True)
class TaskResult:
    """What one task produced: its records in input order and the calls it made."""

    records: list[dict]
    api_calls: int


@dataclass(frozen=True)
class RowOutcome:
    """What one row produced: metadata per attempt, the kept response and its verdict."""

    metas: list[dict | None]
    text: str | None
    verdict: Verdict


# A generation scheme turns one row of a job into its outcome.
Scheme = Callable[[ChatClient, Job, int], Awaitable[RowOutcome]]


async def run_jobs(jobs: list[Job]) -> tuple[dict[str, TaskResult], float]:
    """Run every task concurrently and return their results with the wall clock time."""
    started = time.monotonic()
    results = await asyncio.gather(*(run_task(job) for job in jobs))
    elapsed = time.monotonic() - started
    return {job.config.name: result for job, result in zip(jobs, results)}, elapsed


async def run_task(job: Job) -> TaskResult:
    """Generate and evaluate every row of one task concurrently, preserving input order."""
    config = job.config
    in_flight = max(1, min(config.rpm, len(job.rows)))
    records: list[dict] = [{} for _ in job.rows]
    indices = iter(range(len(job.rows)))
    limiter = RateLimiter(config.rpm)
    generate = _rejection_sample if config.generation.scheme == "rejection" else _single_attempt

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=in_flight)) as session:
        client = ChatClient(session, config, limiter)
        await asyncio.gather(
            *(_worker(indices, generate, client, job, records) for _ in range(in_flight))
        )
    return TaskResult(records, client.api_calls)


async def _worker(
    indices: Iterator[int], generate: Scheme, client: ChatClient, job: Job, records: list[dict]
) -> None:
    """Process rows until the shared index iterator is exhausted.

    Advancing the iterator never awaits, so on a single threaded event loop each
    index reaches exactly one worker, and rows are claimed in input order.
    """
    for index in indices:
        outcome = await generate(client, job, index)
        records[index] = _record(job.config, job.rows[index], outcome)


async def _single_attempt(client: ChatClient, job: Job, index: int) -> RowOutcome:
    """Greedy and sample: one logical attempt, kept even when it fails evaluation."""
    attempt = await client.complete(job.messages[index])
    if attempt.text is None:
        return RowOutcome([None], None, Verdict(False, None))
    verdict = await evaluate(job.config.evaluation, attempt.text, job.rows[index], index, client)
    return RowOutcome([_meta(attempt, verdict)], attempt.text, verdict)


async def _rejection_sample(client: ChatClient, job: Job, index: int) -> RowOutcome:
    """Keep the first response that passes evaluation, giving up after `n` attempts."""
    metas: list[dict | None] = []
    for _ in range(job.config.generation.n):
        attempt = await client.complete(job.messages[index])
        if attempt.text is None:
            metas.append(None)
            continue
        verdict = await evaluate(job.config.evaluation, attempt.text, job.rows[index], index, client)
        metas.append(_meta(attempt, verdict))
        if verdict.passed:
            return RowOutcome(metas, attempt.text, verdict)
    return RowOutcome(metas, None, Verdict(False, None))


def _meta(attempt: Attempt, verdict: Verdict) -> dict | None:
    """An attempt's metadata, carrying the judge call's own metadata when there was one."""
    if verdict.judge_meta is None:
        return attempt.meta
    return {**attempt.meta, "judge_meta": verdict.judge_meta}


def _record(config: TaskConfig, row: dict, outcome: RowOutcome) -> dict:
    """Shape one output line. Metadata stays a bare object unless several attempts were made."""
    result = {
        "passed": outcome.verdict.passed,
        "extracted_answer": outcome.verdict.extracted,
        "attempts": len(outcome.metas),
    }
    if config.evaluation is not None and config.evaluation.type == "llm_judge":
        result["judge_score"] = outcome.verdict.judge_score
    return {
        "input": row,
        "output": None if outcome.text is None else {config.output_field: outcome.text},
        "result": result,
        "meta": outcome.metas[0] if len(outcome.metas) == 1 else outcome.metas,
    }


def summarize(results: dict[str, TaskResult], elapsed: float, per_task: bool) -> dict:
    """Build the JSON summary printed once a run finishes."""
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
            name: {**_counts(result.records), "total_api_calls": result.api_calls}
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
