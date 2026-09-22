"""Orchestration: run every selected task concurrently over its input rows."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from rejlib.api import ApiClient, Stats
from rejlib.config import RateLimits, TaskConfig
from rejlib.cost import FREE, Ledger
from rejlib.evaluation import Evaluator, build_evaluator
from rejlib.progress import Progress
from rejlib.rows import TaskRun, output_row
from rejlib.scheduler import Scheduler
from rejlib.schemes import generate

MIN_IN_FLIGHT = 8
MAX_IN_FLIGHT = 256
TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=300.0)


def in_flight_limit(limits: RateLimits) -> int:
    """How many rows may be in flight: the hard cap when one is configured, else
    one minute of request budget, clamped (T1, T73)."""
    if limits.max_concurrent is not None:
        return limits.max_concurrent
    if limits.rpm is None:
        return MAX_IN_FLIGHT
    return max(MIN_IN_FLIGHT, min(limits.rpm, MAX_IN_FLIGHT))


@dataclass(frozen=True)
class _Worker:
    """Everything one task's rows are processed with."""

    client: ApiClient
    config: TaskConfig
    evaluator: Evaluator | None
    ledger: Ledger
    progress: Progress | None
    results: list
    semaphore: asyncio.Semaphore


async def run_tasks(tasks: dict[str, TaskConfig], inputs: dict[str, list[dict]],
                    ledger: Ledger, progress: Progress | None = None) -> dict[str, TaskRun]:
    """Run every task concurrently, each with its own rate budget (T30)."""
    capacity = sum(in_flight_limit(task.rate_limits) for task in tasks.values())
    limits = httpx.Limits(max_connections=capacity, max_keepalive_connections=capacity)
    async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as http:
        async with _ticking(progress):
            runs = await asyncio.gather(*(
                _run_task(http, config, inputs[name], ledger, progress)
                for name, config in tasks.items()
            ))
    return dict(zip(tasks, runs))


@asynccontextmanager
async def _ticking(progress: Progress | None):
    """Keep progress reporting alive on its timer for as long as rows are running."""
    if progress is None:
        yield
        return

    ticker = asyncio.create_task(progress.ticker())
    try:
        yield
    finally:
        ticker.cancel()


async def _run_task(http: httpx.AsyncClient, config: TaskConfig, rows: list[dict],
                    ledger: Ledger, progress: Progress | None) -> TaskRun:
    """Process every row of one task and return its output rows in input order."""
    stats = Stats()
    scheduler = Scheduler(config.rate_limits, config.cost or FREE, ledger)
    client = ApiClient(http, config, scheduler, stats)
    if progress is not None:
        progress.track(stats)

    worker = _Worker(
        client=client,
        config=config,
        evaluator=build_evaluator(config, client),
        ledger=ledger,
        progress=progress,
        results=[None] * len(rows),
        semaphore=asyncio.Semaphore(in_flight_limit(config.rate_limits)),
    )
    await _dispatch(worker, rows)
    return TaskRun([row for row in worker.results if row is not None], stats)


async def _dispatch(worker: _Worker, rows: list[dict]) -> None:
    """Start one job per row, in input order, and wait for all of them.

    Tasks are created in input order and each one's first action is to take a
    slot in the rate limiter, so requests also leave in input order. The budget
    is checked once a row may actually start, so no row is started after it ran
    out (T75).
    """
    pending = []
    for index, row in enumerate(rows):
        await worker.semaphore.acquire()
        if worker.ledger.exhausted:
            worker.semaphore.release()
            break
        pending.append(asyncio.create_task(_process_row(worker, row, index)))
    await asyncio.gather(*pending)


async def _process_row(worker: _Worker, row: dict, index: int) -> None:
    """Generate for one row and store its output row at the row's own index.

    A row the budget stopped before it could send anything produced no result,
    so nothing is written for it.
    """
    try:
        outcome = await generate(worker.client, worker.config, worker.evaluator, row)
    finally:
        worker.semaphore.release()
    if not outcome.attempts:
        return

    worker.results[index] = output_row(worker.config, row, outcome)
    if worker.progress is not None:
        worker.progress.row_done(worker.results[index])
