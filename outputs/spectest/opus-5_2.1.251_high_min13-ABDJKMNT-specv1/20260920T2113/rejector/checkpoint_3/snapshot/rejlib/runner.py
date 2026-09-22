"""Orchestration: run every selected task concurrently over its input rows."""

from __future__ import annotations

import asyncio

import httpx

from rejlib.api import ChatClient, Stats
from rejlib.config import TaskConfig
from rejlib.evaluation import Evaluator, build_evaluator
from rejlib.ratelimit import RateLimiter
from rejlib.rows import TaskRun, output_row
from rejlib.schemes import generate

MIN_IN_FLIGHT = 8
MAX_IN_FLIGHT = 256
TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=300.0)


def in_flight_limit(rpm: int) -> int:
    """How many rows may be in flight: one minute of budget, clamped (T1)."""
    return max(MIN_IN_FLIGHT, min(rpm, MAX_IN_FLIGHT))


async def run_tasks(tasks: dict[str, TaskConfig],
                    inputs: dict[str, list[dict]]) -> dict[str, TaskRun]:
    """Run every task concurrently, each with its own rate budget (T30)."""
    capacity = sum(in_flight_limit(task.rpm) for task in tasks.values())
    limits = httpx.Limits(max_connections=capacity, max_keepalive_connections=capacity)
    async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as http:
        runs = await asyncio.gather(
            *(_run_task(http, config, inputs[name]) for name, config in tasks.items())
        )
    return dict(zip(tasks, runs))


async def _run_task(http: httpx.AsyncClient, config: TaskConfig,
                    rows: list[dict]) -> TaskRun:
    """Process every row of one task and return its output rows in input order."""
    stats = Stats()
    limiter = RateLimiter(config.rpm)
    client = ChatClient(http, config, limiter, stats)
    evaluator = build_evaluator(config, client)
    results: list[dict | None] = [None] * len(rows)
    semaphore = asyncio.Semaphore(in_flight_limit(config.rpm))

    pending = []
    # Tasks are created in input order and each one's first action is to take a
    # rate-limiter token, so requests also leave in input order.
    for index, row in enumerate(rows):
        await semaphore.acquire()
        pending.append(asyncio.create_task(
            _process_row(client, config, evaluator, row, index, results, semaphore)
        ))
    await asyncio.gather(*pending)
    return TaskRun(results, stats)


async def _process_row(client: ChatClient, config: TaskConfig, evaluator: Evaluator | None,
                       row: dict, index: int, results: list,
                       semaphore: asyncio.Semaphore) -> None:
    try:
        outcome = await generate(client, config, evaluator, row)
    finally:
        semaphore.release()
    results[index] = output_row(config, row, outcome)
