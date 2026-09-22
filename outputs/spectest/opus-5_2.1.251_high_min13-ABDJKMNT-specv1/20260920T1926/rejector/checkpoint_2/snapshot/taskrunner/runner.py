"""Concurrent execution of one or more tasks over their input rows.

Rows are handed to a pool of workers in input order, so requests go out in
input order while many stay in flight; each worker keeps its own row's
response, which is what preserves the input/output pairing. Tasks share a
session and run at the same time, so their requests interleave freely.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Sequence

import aiohttp

from .api import CallWindow, ChatClient
from .config import TaskConfig
from .generation import RowOutcome, generate_row

# Upper bound on simultaneous connections per task, so a huge rpm cannot
# exhaust sockets on the client side.
MAX_CONCURRENCY = 256


@dataclass(frozen=True)
class TaskJob:
    """One task paired with the rows it was given."""

    name: str
    config: TaskConfig
    rows: list[dict[str, Any]]


def concurrency_for(rpm: int, row_count: int) -> int:
    """In-flight requests needed to keep a server of capacity `rpm` busy."""
    return max(1, min(rpm, MAX_CONCURRENCY, row_count))


async def execute(jobs: Sequence[TaskJob]) -> tuple[dict[str, list[RowOutcome]], float]:
    """Run every job and return its outcomes plus the run's elapsed time."""
    window = CallWindow()
    in_flight = sum(concurrency_for(job.config.rpm, len(job.rows)) for job in jobs)
    connector = aiohttp.TCPConnector(limit=max(in_flight, 1))
    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(*(_run_job(session, window, job) for job in jobs))
    return {job.name: outcomes for job, outcomes in zip(jobs, results)}, window.elapsed


async def _run_job(
    session: aiohttp.ClientSession, window: CallWindow, job: TaskJob
) -> list[RowOutcome]:
    config = job.config
    client = ChatClient(
        session, config.api_url, config.model, config.generation.max_tokens, window
    )
    workers = concurrency_for(config.rpm, len(job.rows))
    return await _process_rows(client, _judge_client(session, window, config), job, workers)


def _judge_client(
    session: aiohttp.ClientSession, window: CallWindow, config: TaskConfig
) -> ChatClient | None:
    """A second client for `llm_judge` tasks, on the task's model by default."""
    judge = config.evaluation.judge if config.evaluation else None
    if judge is None:
        return None
    return ChatClient(
        session,
        config.api_url,
        judge.model or config.model,
        config.generation.max_tokens,
        window,
    )


async def _process_rows(
    client: ChatClient, judge: ChatClient | None, job: TaskJob, workers: int
) -> list[RowOutcome]:
    pending: asyncio.Queue[int] = asyncio.Queue()
    for index in range(len(job.rows)):
        pending.put_nowait(index)
    outcomes: list[RowOutcome | None] = [None] * len(job.rows)

    async def worker() -> None:
        while not pending.empty():
            index = pending.get_nowait()
            outcomes[index] = await generate_row(client, judge, job.config, job.rows[index])

    await asyncio.gather(*(worker() for _ in range(workers)))
    return outcomes
