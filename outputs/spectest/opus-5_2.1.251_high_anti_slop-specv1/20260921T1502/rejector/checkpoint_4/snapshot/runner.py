"""Concurrent execution of the planned tasks."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Iterator

import aiohttp

from client import ApiClient, RateLimiter, client_for
from jobs import Job
from records import record
from schemes import Scheme, scheme_for


@dataclass(frozen=True)
class TaskResult:
    """What one task produced: its records in input order and the calls it made."""

    records: list[dict]
    api_calls: int


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
    generate = scheme_for(config)

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=in_flight)) as session:
        client = client_for(session, config, limiter)
        await asyncio.gather(
            *(_worker(indices, generate, client, job, records) for _ in range(in_flight))
        )
    return TaskResult(records, client.api_calls)


async def _worker(
    indices: Iterator[int], generate: Scheme, client: ApiClient, job: Job, records: list[dict]
) -> None:
    """Process rows until the shared index iterator is exhausted.

    Advancing the iterator never awaits, so on a single threaded event loop each
    index reaches exactly one worker, and rows are claimed in input order.
    """
    for index in indices:
        outcome = await generate(client, job, index)
        records[index] = record(job.config, job.rows[index], outcome)
