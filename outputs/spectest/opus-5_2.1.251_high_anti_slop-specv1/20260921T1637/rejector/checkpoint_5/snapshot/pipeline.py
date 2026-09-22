"""Concurrent execution of the selected tasks across their input rows."""

import asyncio
from typing import Any

import httpx

from accounting import CallStats, CostTracker, Meter
from api import ChatClient, CompletionsClient, ModelClient
from config import RateLimits, TaskConfig
from jobs import TaskJob
from progress import Progress
from ratelimit import RateLimiter
from results import Outcome, build_summary, task_totals, write_results
from schemes import generate_row

#: Upper bound on concurrent workers per task, so a huge budget cannot spawn unbounded tasks.
MAX_WORKERS = 256
REQUEST_TIMEOUT = httpx.Timeout(300.0, connect=10.0)

#: One task's finished rows, in input order, and the API counters it accumulated.
JobResult = tuple[list[Outcome], CallStats]


async def run_jobs(
    jobs: list[TaskJob], multi: bool, *, show_progress: bool = False, resumed: bool = False
) -> dict[str, Any]:
    """Run every job concurrently, write each one's JSONL results, and return the run summary."""
    tracker = CostTracker(job.task.cost for job in jobs)
    meters = [Meter(job.task.cost, tracker) for job in jobs]
    progress = Progress(
        sum(len(job.rows) for job in jobs),
        [meter.stats for meter in meters],
        tracker,
        enabled=show_progress,
        evaluated=any(job.task.graded for job in jobs),
    )

    connections = sum(_worker_count(job.task.limits, len(job.rows)) for job in jobs)
    limits = httpx.Limits(max_connections=connections, max_keepalive_connections=connections)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, limits=limits) as http:
        completed = await asyncio.gather(
            *(_run_job(http, job, meter, tracker, progress) for job, meter in zip(jobs, meters))
        )
    return _summarize(jobs, completed, multi, tracker, resumed)


async def _run_job(
    http: httpx.AsyncClient,
    job: TaskJob,
    meter: Meter,
    tracker: CostTracker,
    progress: Progress,
) -> JobResult:
    """Run one task over its rows with its own request budget, then write its output file."""
    task = job.task
    limiter = RateLimiter(task.limits)
    client = _client(http, limiter, meter, task, task.model)
    judge = _judge_client(http, limiter, meter, task)

    pending: asyncio.Queue[int] = asyncio.Queue()
    for index in range(len(job.rows)):
        pending.put_nowait(index)
    outcomes: dict[int, Outcome] = {}

    async def worker() -> None:
        """Take row indices in input order until the queue drains or the budget runs out."""
        while not tracker.exhausted:
            try:
                index = pending.get_nowait()
            except asyncio.QueueEmpty:
                return
            outcome = await generate_row(
                client, judge, task, job.prompts[index], job.setups, job.rows[index]
            )
            outcomes[index] = outcome
            progress.count_row(outcome)

    await asyncio.gather(*(worker() for _ in range(_worker_count(task.limits, len(job.rows)))))

    ordered = _finished_prefix(outcomes)
    write_results(job.output_path, ordered, task.output_field, job.resume_from)
    return ordered, meter.stats


def _finished_prefix(outcomes: dict[int, Outcome]) -> list[Outcome]:
    """The rows finished in input order, stopping at the first one that was never started.

    Every row is normally there; a run that stopped on its budget keeps only the
    unbroken run of leading rows, so the output file stays aligned with the
    input and can be resumed from.
    """
    ordered = []
    while len(ordered) in outcomes:
        ordered.append(outcomes[len(ordered)])
    return ordered


def _judge_client(
    http: httpx.AsyncClient, limiter: RateLimiter, meter: Meter, task: TaskConfig
) -> ModelClient | None:
    """A second client bound to the judge model, sharing the task's rate budget and counters."""
    evaluation = task.evaluation
    if evaluation is None or evaluation.judge_model is None:
        return None
    return _client(http, limiter, meter, task, evaluation.judge_model)


def _client(
    http: httpx.AsyncClient, limiter: RateLimiter, meter: Meter, task: TaskConfig, model: str
) -> ModelClient:
    """A client for the task's API flavour, bound to ``model``."""
    if task.api_type == "completions":
        return CompletionsClient(http, limiter, meter, task.api_url, model, task.chat_template)
    return ChatClient(http, limiter, meter, task.api_url, model)


def _summarize(
    jobs: list[TaskJob],
    completed: list[JobResult],
    multi: bool,
    tracker: CostTracker,
    resumed: bool,
) -> dict[str, Any]:
    """Aggregate every job into the stdout summary, adding per-task totals for multi-task runs."""
    overall = CallStats()
    for _, stats in completed:
        overall.merge(stats)
    outcomes = [outcome for rows, _ in completed for outcome in rows]

    summary = build_summary(
        outcomes,
        overall.api_calls,
        overall.elapsed_seconds,
        cost=tracker.to_json() if tracker.enabled else None,
        resumed_from=sum(job.resume_from for job in jobs) if resumed else None,
    )
    if multi:
        summary["tasks"] = {
            job.task.name: task_totals(rows, stats.api_calls)
            for job, (rows, stats) in zip(jobs, completed)
        }
    return summary


def _worker_count(limits: RateLimits, rows: int) -> int:
    """How many rows a task keeps in flight at once.

    One worker owns one row at a time, and a row's requests are sequential, so
    the pool size is also the cap on the task's in-flight requests: an explicit
    ``max_concurrent`` sets it, otherwise a minute of request budget is kept in
    flight, bounded by the work available and by :data:`MAX_WORKERS`.
    """
    cap = limits.max_concurrent or limits.rpm or MAX_WORKERS
    return max(1, min(rows, cap, MAX_WORKERS))
