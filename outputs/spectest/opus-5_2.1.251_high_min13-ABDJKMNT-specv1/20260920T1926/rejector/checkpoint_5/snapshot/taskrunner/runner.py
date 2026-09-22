"""Concurrent execution of one or more tasks over their input rows.

Rows are handed to a pool of workers in input order, so requests go out in
input order while many stay in flight; each worker keeps its own row's
response, which is what preserves the input/output pairing. Tasks share a
session and run at the same time, so their requests interleave freely, but
each enforces its own rate limits.

A worker stops pulling rows as soon as the run's budget is spent. Rows that
were never started produce nothing, so a run reports the leading rows it
actually completed.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Sequence

import aiohttp

from .api import ChatClient, CompletionsClient, ModelClient
from .config import RateLimitConfig, TaskConfig
from .cost import CostTracker
from .generation import RowOutcome, generate_row
from .limits import UNCAPPED_CONCURRENCY, CallWindow, RateLimiter, RequestGate
from .progress import ProgressReporter


@dataclass(frozen=True)
class TaskJob:
    """One task paired with the rows it was given."""

    name: str
    config: TaskConfig
    rows: list[dict[str, Any]]


def concurrency_for(limits: RateLimitConfig, row_count: int) -> int:
    """Workers needed to keep a task's request budget busy, within its cap."""
    cap = limits.max_concurrent or limits.rpm or UNCAPPED_CONCURRENCY
    return max(1, min(cap, UNCAPPED_CONCURRENCY, row_count))


async def execute(
    jobs: Sequence[TaskJob],
    tracker: CostTracker,
    progress: ProgressReporter | None = None,
) -> tuple[dict[str, list[RowOutcome]], float]:
    """Run every job and return its outcomes plus the run's elapsed time."""
    window = CallWindow()
    in_flight = sum(concurrency_for(job.config.limits, len(job.rows)) for job in jobs)
    connector = aiohttp.TCPConnector(limit=max(in_flight, 1))
    async with aiohttp.ClientSession(connector=connector) as session:
        ticker = asyncio.create_task(progress.tick()) if progress else None
        try:
            results = await asyncio.gather(
                *(_run_job(session, window, tracker, progress, job) for job in jobs)
            )
        finally:
            await _stop(ticker)
    return {job.name: outcomes for job, outcomes in zip(jobs, results)}, window.elapsed


async def _stop(ticker: asyncio.Task | None) -> None:
    if ticker is None:
        return
    ticker.cancel()
    with suppress(asyncio.CancelledError):
        await ticker


async def _run_job(
    session: aiohttp.ClientSession,
    window: CallWindow,
    tracker: CostTracker,
    progress: ProgressReporter | None,
    job: TaskJob,
) -> list[RowOutcome]:
    config = job.config
    gate = RequestGate(RateLimiter(config.limits), tracker, config.cost, window)
    client = _client(session, gate, config)
    workers = concurrency_for(config.limits, len(job.rows))
    return await _process_rows(
        client, _judge_client(session, gate, config), job, workers, progress
    )


def _client(
    session: aiohttp.ClientSession,
    gate: RequestGate,
    config: TaskConfig,
    model: str | None = None,
) -> ModelClient:
    """The client the task's `api_type` asks for, on `model` or the task's own."""
    model = model or config.model
    max_tokens = config.generation.max_tokens
    if config.api_type == "completions":
        return CompletionsClient(
            session, config.api_url, model, max_tokens, gate, config.chat_template
        )
    return ChatClient(session, config.api_url, model, max_tokens, gate)


def _judge_client(
    session: aiohttp.ClientSession, gate: RequestGate, config: TaskConfig
) -> ModelClient | None:
    """A second client for `llm_judge` tasks, on the task's model by default."""
    judge = config.evaluation.judge if config.evaluation else None
    if judge is None:
        return None
    return _client(session, gate, config, judge.model)


async def _process_rows(
    client: ModelClient,
    judge: ModelClient | None,
    job: TaskJob,
    workers: int,
    progress: ProgressReporter | None,
) -> list[RowOutcome]:
    pending: asyncio.Queue[int] = asyncio.Queue()
    for index in range(len(job.rows)):
        pending.put_nowait(index)
    outcomes: list[RowOutcome | None] = [None] * len(job.rows)

    async def worker() -> None:
        while not pending.empty() and not client.stopped:
            index = pending.get_nowait()
            outcomes[index] = await generate_row(client, judge, job.config, job.rows[index])
            if progress is not None:
                progress.row_done(outcomes[index].passed_count > 0)

    await asyncio.gather(*(worker() for _ in range(workers)))
    return _completed(outcomes)


def _completed(outcomes: Sequence[RowOutcome | None]) -> list[RowOutcome]:
    """The leading rows that ran; a spent budget leaves the rest untouched."""
    done = 0
    while done < len(outcomes) and outcomes[done] is not None:
        done += 1
    return list(outcomes[:done])
