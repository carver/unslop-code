"""Concurrent execution of every selected task over its input rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from .agentic import LoopResult, run_loop
from .api import REQUEST_TIMEOUT_SECONDS, ModelClient, RunStats
from .config import TaskConfig
from .evaluation import build_evaluator, judge
from .prompts import build_messages
from .solutions import MultiOutcome, collect_solutions

MAX_IN_FLIGHT = 256
MAX_CONNECTIONS = 512


@dataclass
class RowOutcome:
    """What one input row produced."""

    row: dict
    output: str | None
    passed: bool | None
    extracted_answer: str | None
    attempts: int
    judge_score: float | None = None
    metas: list[dict] = field(default_factory=list)
    loop: LoopResult | None = None


@dataclass
class TaskRun:
    """One task's outcomes, in input order."""

    task: TaskConfig
    outcomes: list[RowOutcome | MultiOutcome]


def run_tasks(tasks: list[TaskConfig], rows_by_task: dict) -> tuple[list[TaskRun], RunStats]:
    """Process every task, preserving input order within each one."""
    return asyncio.run(_run(tasks, rows_by_task))


async def _run(tasks: list[TaskConfig], rows_by_task: dict) -> tuple[list[TaskRun], RunStats]:
    budgets = {task.name: _in_flight_limit(task.rpm, len(rows_by_task[task.name])) for task in tasks}
    pool = min(sum(budgets.values()) or 1, MAX_CONNECTIONS)
    limits = httpx.Limits(max_connections=pool, max_keepalive_connections=pool)
    stats = RunStats()

    async with httpx.AsyncClient(limits=limits, timeout=REQUEST_TIMEOUT_SECONDS) as http:
        runs = await asyncio.gather(
            *(
                _run_one(http, stats, task, rows_by_task[task.name], budgets[task.name])
                for task in tasks
            )
        )
    return list(runs), stats


async def _run_one(
    http: httpx.AsyncClient, stats: RunStats, task: TaskConfig, rows: list[dict], in_flight: int
) -> TaskRun:
    """Run one task's rows concurrently, bounded by its own in-flight budget."""
    client = ModelClient(http, task, stats)
    evaluator = build_evaluator(task, client)
    slots = asyncio.Semaphore(in_flight)
    process_row = _row_processor(task)

    async def process(row: dict) -> RowOutcome | MultiOutcome:
        async with slots:
            return await process_row(client, task, evaluator, row)

    outcomes = await asyncio.gather(*(process(row) for row in rows))
    return TaskRun(task, list(outcomes))


def _row_processor(task: TaskConfig):
    """The per-row coroutine this task's format and scheme call for."""
    if task.list_format:
        return collect_solutions
    return _process_agentic_row if task.generation.scheme == "agentic" else _process_row


def _in_flight_limit(rpm: int, row_count: int) -> int:
    """Concurrency budget: enough to saturate a server rated at `rpm`.

    The server queues internally and never rate-limits, so the only cost of a
    deep pipeline is memory; capacity equal to `rpm` keeps at most a minute of
    work queued while leaving no slot idle.
    """
    return max(1, min(rpm, MAX_IN_FLIGHT, row_count or 1))


async def _process_agentic_row(
    client: ModelClient, task: TaskConfig, evaluator, row: dict
) -> RowOutcome:
    """Run one agentic loop for a row; the loop replaces the attempt budget."""
    loop = await run_loop(client, task, row)
    verdict = await judge(evaluator, loop.output, row)
    if verdict.judge_meta is not None:
        loop.meta["judge_meta"] = verdict.judge_meta

    return RowOutcome(
        row, loop.output, verdict.passed, verdict.extracted, 1, verdict.judge_score, [loop.meta], loop
    )


async def _process_row(client: ModelClient, task: TaskConfig, evaluator, row: dict) -> RowOutcome:
    """Generate one solution for a row, retrying under rejection until it passes."""
    messages = build_messages(task.prompt, row)
    is_rejection = task.generation.scheme == "rejection"
    metas: list[dict] = []

    for attempt in range(1, task.generation.legacy_attempts + 1):
        completion = await client.complete(messages)
        if completion is None:
            return RowOutcome(row, None, False, None, attempt, metas=metas)

        metas.append(completion.meta)
        verdict = await judge(evaluator, completion.text, row)
        if verdict.judge_meta is not None:
            completion.meta["judge_meta"] = verdict.judge_meta
        if verdict.passed is not False or not is_rejection:
            return RowOutcome(
                row, completion.text, verdict.passed, verdict.extracted, attempt,
                verdict.judge_score, metas,
            )

    return RowOutcome(row, None, False, None, task.generation.legacy_attempts, metas=metas)
