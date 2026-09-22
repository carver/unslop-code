"""Concurrent execution of the planned tasks."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Iterator

import aiohttp

from client import ApiClient, client_for
from cost import Ledger
from jobs import Job
from limits import Limiter
from progress import Progress
from records import record, row_passed
from schemes import Scheme, scheme_for


@dataclass(frozen=True)
class TaskResult:
    """What one task produced: its records in input order, its calls and its spend."""

    records: list[dict]
    api_calls: int
    ledger: Ledger
    resumed_from: int


async def run_jobs(jobs: list[Job], progress: bool = False) -> tuple[dict[str, TaskResult], float]:
    """Run every task concurrently and return their results with the wall clock time."""
    ledgers = [Ledger(job.config.cost) for job in jobs]
    reporter = Progress(
        total=sum(len(job.rows) for job in jobs),
        evaluated=any(job.config.evaluation is not None for job in jobs),
        ledgers=ledgers,
        enabled=progress,
    )

    started = time.monotonic()
    results = await asyncio.gather(
        *(run_task(job, ledger, reporter) for job, ledger in zip(jobs, ledgers))
    )
    elapsed = time.monotonic() - started
    return {job.config.name: result for job, result in zip(jobs, results)}, elapsed


async def run_task(job: Job, ledger: Ledger, progress: Progress) -> TaskResult:
    """Generate and evaluate every row of one task concurrently, preserving input order.

    The task runs `max_concurrent` workers, so that many requests are in flight
    at most however much room the rate limits leave; an agentic row holds its
    worker for the whole of its loop.
    """
    config = job.config
    workers = max(1, min(config.rate_limits.max_concurrent, len(job.rows)))
    records: list[dict] = [{} for _ in job.rows]
    indices = iter(range(len(job.rows)))
    limiter = Limiter(config.rate_limits)
    generate = scheme_for(config)

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=workers)) as session:
        client = client_for(session, config, limiter, ledger, progress)
        await asyncio.gather(
            *(_worker(indices, generate, client, job, records, progress) for _ in range(workers))
        )
    # A spent budget stops the workers from claiming further rows, and rows are
    # claimed in order, so what was processed is a prefix of the input.
    return TaskResult([row for row in records if row], client.api_calls, ledger, job.resumed_from)


async def _worker(
    indices: Iterator[int],
    generate: Scheme,
    client: ApiClient,
    job: Job,
    records: list[dict],
    progress: Progress,
) -> None:
    """Process rows until the shared index iterator is exhausted or the budget is spent.

    Advancing the iterator never awaits, so on a single threaded event loop each
    index reaches exactly one worker, and rows are claimed in input order.
    """
    for index in indices:
        if client.ledger.exhausted:
            return
        outcome = await generate(client, job, index)
        records[index] = record(job.config, job.rows[index], outcome)
        progress.row(row_passed(records[index]))
