"""Concurrent execution of a task across input rows."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterator

import aiohttp

from client import Attempt, ChatClient, RateLimiter
from config import TaskConfig
from evaluation import judge


@dataclass(frozen=True)
class RunStats:
    """Execution totals that the per row records do not carry themselves."""

    api_calls: int
    elapsed_seconds: float


@dataclass(frozen=True)
class RowOutcome:
    """What one row produced: every attempt made, plus the response that was kept."""

    attempts: list[Attempt]
    text: str | None
    passed: bool | None
    extracted: str | None


# A generation scheme turns one row into its outcome.
Scheme = Callable[[ChatClient, TaskConfig, dict, list[dict]], Awaitable[RowOutcome]]


async def run_task(
    config: TaskConfig, rows: list[dict], messages: list[list[dict]]
) -> tuple[list[dict], RunStats]:
    """Generate and evaluate every row concurrently, preserving input order."""
    in_flight = max(1, min(config.rpm, len(rows)))
    records: list[dict] = [{} for _ in rows]
    indices = iter(range(len(rows)))
    limiter = RateLimiter(config.rpm)
    generate = _rejection_sample if config.generation.scheme == "rejection" else _single_attempt

    started = time.monotonic()
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=in_flight)) as session:
        client = ChatClient(session, config, limiter)
        await asyncio.gather(
            *(
                _worker(indices, generate, client, config, rows, messages, records)
                for _ in range(in_flight)
            )
        )
    return records, RunStats(client.api_calls, time.monotonic() - started)


async def _worker(
    indices: Iterator[int],
    generate: Scheme,
    client: ChatClient,
    config: TaskConfig,
    rows: list[dict],
    messages: list[list[dict]],
    records: list[dict],
) -> None:
    """Process rows until the shared index iterator is exhausted.

    Advancing the iterator never awaits, so on a single threaded event loop each
    index reaches exactly one worker, and rows are claimed in input order.
    """
    for index in indices:
        outcome = await generate(client, config, rows[index], messages[index])
        records[index] = _record(config, rows[index], outcome)


async def _single_attempt(
    client: ChatClient, config: TaskConfig, row: dict, messages: list[dict]
) -> RowOutcome:
    """Greedy and sample: one logical attempt, kept even when it fails evaluation."""
    attempt = await client.complete(messages)
    if attempt.text is None:
        return RowOutcome([attempt], None, False, None)
    passed, extracted = judge(config.evaluation, attempt.text, row)
    return RowOutcome([attempt], attempt.text, passed, extracted)


async def _rejection_sample(
    client: ChatClient, config: TaskConfig, row: dict, messages: list[dict]
) -> RowOutcome:
    """Keep the first response that passes evaluation, giving up after `n` attempts."""
    attempts: list[Attempt] = []
    for _ in range(config.generation.n):
        attempt = await client.complete(messages)
        attempts.append(attempt)
        if attempt.text is None:
            continue
        passed, extracted = judge(config.evaluation, attempt.text, row)
        if passed:
            return RowOutcome(attempts, attempt.text, True, extracted)
    return RowOutcome(attempts, None, False, None)


def _record(config: TaskConfig, row: dict, outcome: RowOutcome) -> dict:
    """Shape one output line. Metadata stays a bare object unless several attempts were made."""
    metas = [attempt.meta for attempt in outcome.attempts]
    return {
        "input": row,
        "output": None if outcome.text is None else {config.output_field: outcome.text},
        "result": {
            "passed": outcome.passed,
            "extracted_answer": outcome.extracted,
            "attempts": len(outcome.attempts),
        },
        "meta": metas[0] if len(metas) == 1 else metas,
    }


def summarize(records: list[dict], stats: RunStats) -> dict:
    """Build the JSON summary printed once a run finishes."""
    metas = []
    for record in records:
        meta = record["meta"]
        metas.extend(meta if isinstance(meta, list) else [meta])
    metas = [meta for meta in metas if meta is not None]

    # Without an evaluation a row passes as long as the API answered it.
    passed = sum(
        1
        for record in records
        if record["result"]["passed"]
        or (record["result"]["passed"] is None and record["output"] is not None)
    )
    elapsed = stats.elapsed_seconds
    return {
        "total": len(records),
        "passed": passed,
        "failed": len(records) - passed,
        "total_prompt_tokens": sum(meta["prompt_tokens"] for meta in metas),
        "total_completion_tokens": sum(meta["completion_tokens"] for meta in metas),
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.api_calls / elapsed * 60, 1) if elapsed else 0.0,
    }
