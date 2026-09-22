"""Concurrent execution of the selected tasks across their input rows."""

import asyncio
from typing import Any

import httpx

from api import CallStats, ChatClient
from config import TaskConfig
from jobs import TaskJob
from ratelimit import RateLimiter
from results import RowOutcome, build_summary, task_totals, write_results
from schemes import generate_row

#: Upper bound on concurrent workers per task, so a huge ``rpm`` cannot spawn unbounded tasks.
MAX_WORKERS = 256
REQUEST_TIMEOUT = httpx.Timeout(300.0, connect=10.0)

#: One task's finished rows, in input order, and the API counters it accumulated.
JobResult = tuple[list[RowOutcome], CallStats]


async def run_jobs(jobs: list[TaskJob], multi: bool) -> dict[str, Any]:
    """Run every job concurrently, write each one's JSONL results, and return the run summary."""
    connections = sum(_worker_count(job.task.rpm, len(job.rows)) for job in jobs)
    limits = httpx.Limits(max_connections=connections, max_keepalive_connections=connections)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, limits=limits) as http:
        completed = await asyncio.gather(*(_run_job(http, job) for job in jobs))
    return _summarize(jobs, completed, multi)


async def _run_job(http: httpx.AsyncClient, job: TaskJob) -> JobResult:
    """Run one task over its rows with its own request budget, then write its output file."""
    task = job.task
    stats = CallStats()
    limiter = RateLimiter(task.rpm)
    client = ChatClient(http, limiter, task.api_url, task.model, stats)
    judge = _judge_client(http, limiter, task, stats)

    pending: asyncio.Queue[int] = asyncio.Queue()
    for index in range(len(job.rows)):
        pending.put_nowait(index)
    outcomes: dict[int, RowOutcome] = {}
    workers = _worker_count(task.rpm, len(job.rows))
    await asyncio.gather(*(_worker(pending, client, judge, job, outcomes) for _ in range(workers)))

    ordered = [outcomes[index] for index in range(len(job.rows))]
    write_results(job.output_path, ordered, task.output_field)
    return ordered, stats


async def _worker(
    pending: asyncio.Queue[int],
    client: ChatClient,
    judge: ChatClient | None,
    job: TaskJob,
    outcomes: dict[int, RowOutcome],
) -> None:
    """Take row indices in input order until the queue is drained."""
    while True:
        try:
            index = pending.get_nowait()
        except asyncio.QueueEmpty:
            return
        outcomes[index] = await generate_row(
            client, judge, job.task, job.prompts[index], job.rows[index]
        )


def _judge_client(
    http: httpx.AsyncClient, limiter: RateLimiter, task: TaskConfig, stats: CallStats
) -> ChatClient | None:
    """A second client bound to the judge model, sharing the task's rate budget and counters."""
    evaluation = task.evaluation
    if evaluation is None or evaluation.judge_model is None:
        return None
    return ChatClient(http, limiter, task.api_url, evaluation.judge_model, stats)


def _summarize(jobs: list[TaskJob], completed: list[JobResult], multi: bool) -> dict[str, Any]:
    """Aggregate every job into the stdout summary, adding per-task totals for multi-task runs."""
    overall = CallStats()
    for _, stats in completed:
        overall.merge(stats)
    outcomes = [outcome for rows, _ in completed for outcome in rows]

    summary = build_summary(outcomes, overall.api_calls, overall.elapsed_seconds)
    if multi:
        summary["tasks"] = {
            job.task.name: task_totals(rows, stats.api_calls)
            for job, (rows, stats) in zip(jobs, completed)
        }
    return summary


def _worker_count(rpm: int, rows: int) -> int:
    """Enough workers to keep a minute of request budget in flight, bounded by the work available."""
    return max(1, min(rows, rpm, MAX_WORKERS))
