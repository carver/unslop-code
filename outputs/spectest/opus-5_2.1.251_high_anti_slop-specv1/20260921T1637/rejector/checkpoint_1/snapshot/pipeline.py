"""Concurrent execution of a task across its input rows."""

import asyncio
from typing import Any

import httpx

from api import CallStats, ChatClient
from config import TaskConfig
from dataset import Messages, Row
from ratelimit import RateLimiter
from results import RowOutcome, build_summary, write_results
from schemes import generate_row

#: Upper bound on concurrent workers, so a huge ``rpm`` cannot spawn unbounded tasks.
MAX_WORKERS = 256
REQUEST_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


async def run_task(
    task: TaskConfig, rows: list[Row], prompts: list[Messages], output_path: str
) -> dict[str, Any]:
    """Run every row concurrently, write the JSONL results, and return the run summary."""
    workers = _worker_count(task.rpm, len(rows))
    stats = CallStats()
    limiter = RateLimiter(task.rpm)
    pending: asyncio.Queue[int] = asyncio.Queue()
    for index in range(len(rows)):
        pending.put_nowait(index)
    outcomes: dict[int, RowOutcome] = {}

    limits = httpx.Limits(max_connections=workers, max_keepalive_connections=workers)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, limits=limits) as http:
        client = ChatClient(http, limiter, task.api_url, task.model, stats)
        await asyncio.gather(
            *(_worker(pending, client, task, rows, prompts, outcomes) for _ in range(workers))
        )

    ordered = [outcomes[index] for index in range(len(rows))]
    write_results(output_path, ordered, task.output_field)
    return build_summary(ordered, stats.api_calls, stats.elapsed_seconds)


async def _worker(
    pending: asyncio.Queue[int],
    client: ChatClient,
    task: TaskConfig,
    rows: list[Row],
    prompts: list[Messages],
    outcomes: dict[int, RowOutcome],
) -> None:
    """Take row indices in input order until the queue is drained."""
    while True:
        try:
            index = pending.get_nowait()
        except asyncio.QueueEmpty:
            return
        outcomes[index] = await generate_row(client, task, prompts[index], rows[index])


def _worker_count(rpm: int, rows: int) -> int:
    """Enough workers to keep a minute of request budget in flight, bounded by the work available."""
    return max(1, min(rows, rpm, MAX_WORKERS))
