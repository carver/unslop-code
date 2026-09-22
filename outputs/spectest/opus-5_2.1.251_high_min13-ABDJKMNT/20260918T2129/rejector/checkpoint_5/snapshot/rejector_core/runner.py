"""Concurrent execution of every selected task over its input rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from itertools import takewhile

import httpx

from .agentic import LoopResult, run_loop
from .api import REQUEST_TIMEOUT_SECONDS, ModelClient, RunStats
from .config import TaskConfig
from .cost import CostTracker, build_tracker
from .evaluation import Verdict, assess, build_evaluator
from .limits import RateLimiter
from .progress import Progress
from .prompts import build_messages
from .solutions import MultiOutcome, collect_solutions

MAX_IN_FLIGHT = 256
MAX_CONNECTIONS = 512
FALLBACK_RPM = 60

# Stands in for a row the exhausted budget stopped before it was dispatched.
SKIPPED = object()


@dataclass
class RowOutcome:
    """What one input row produced."""

    row: dict
    output: object
    passed: bool | None
    extracted_answer: str | None
    attempts: int
    judge_score: float | None = None
    metas: list[dict] = field(default_factory=list)
    loop: LoopResult | None = None
    schema_valid: bool | None = None
    schema_error: str | None = None


@dataclass
class TaskRun:
    """One task's outcomes, in input order."""

    task: TaskConfig
    outcomes: list[RowOutcome | MultiOutcome]


def run_tasks(
    tasks: list[TaskConfig], rows_by_task: dict, progress: bool = False
) -> tuple[list[TaskRun], RunStats, CostTracker]:
    """Process every task, preserving input order within each one."""
    return asyncio.run(_run(tasks, rows_by_task, progress))


def outcome_passed(outcome: RowOutcome | MultiOutcome) -> bool:
    """A row passes once it holds a response that evaluation did not reject.

    In the multi-solution format that means at least one passing solution;
    without an evaluation every emitted solution counts as passing.
    """
    if isinstance(outcome, MultiOutcome):
        return outcome.passed > 0
    return outcome.output is not None and outcome.passed is not False


async def _run(
    tasks: list[TaskConfig], rows_by_task: dict, show_progress: bool
) -> tuple[list[TaskRun], RunStats, CostTracker]:
    limiters = {
        task.name: RateLimiter(task.rate_limits, _in_flight_limit(task, len(rows_by_task[task.name])))
        for task in tasks
    }
    pool = min(sum(limiter.concurrency for limiter in limiters.values()) or 1, MAX_CONNECTIONS)
    stats = RunStats()
    costs = build_tracker(tasks)
    progress = Progress(
        total=sum(len(rows) for rows in rows_by_task.values()),
        stats=stats,
        costs=costs,
        show_results=any(task.evaluation or task.output_schema for task in tasks),
        enabled=show_progress,
    )

    limits = httpx.Limits(max_connections=pool, max_keepalive_connections=pool)
    async with httpx.AsyncClient(limits=limits, timeout=REQUEST_TIMEOUT_SECONDS) as http:
        async with progress.reporting():
            runs = await asyncio.gather(
                *(
                    _run_one(http, stats, task, rows_by_task[task.name], limiters[task.name], costs, progress)
                    for task in tasks
                )
            )
    return list(runs), stats, costs


async def _run_one(
    http: httpx.AsyncClient,
    stats: RunStats,
    task: TaskConfig,
    rows: list[dict],
    limiter: RateLimiter,
    costs: CostTracker,
    progress: Progress,
) -> TaskRun:
    """Run one task's rows concurrently, bounded by its own in-flight budget.

    A row holds one concurrency slot for as long as it takes, which is what
    keeps an agentic loop to a single slot across all of its iterations.  Once
    the budget is spent the rows still queued are never dispatched, and the
    task writes the prefix that did run.
    """
    client = ModelClient(http, task, stats, limiter, costs)
    evaluator = build_evaluator(task, client)
    process_row = _row_processor(task)

    async def process(row: dict):
        async with limiter.slot():
            if costs.exhausted:
                return SKIPPED
            outcome = await process_row(client, task, evaluator, row)
        progress.record(outcome_passed(outcome))
        return outcome

    outcomes = await asyncio.gather(*(process(row) for row in rows))
    return TaskRun(task, list(takewhile(lambda outcome: outcome is not SKIPPED, outcomes)))


def _row_processor(task: TaskConfig):
    """The per-row coroutine this task's format and scheme call for."""
    if task.list_format:
        return collect_solutions
    return _process_agentic_row if task.generation.scheme == "agentic" else _process_row


def _in_flight_limit(task: TaskConfig, row_count: int) -> int:
    """Concurrency budget for a task that configures no `max_concurrent`.

    The server queues internally and never rate-limits, so the only cost of a
    deep pipeline is memory; capacity equal to `rpm` keeps at most a minute of
    work queued while leaving no slot idle.
    """
    return max(1, min(task.rate_limits.rpm or FALLBACK_RPM, MAX_IN_FLIGHT, row_count or 1))


async def _process_agentic_row(
    client: ModelClient, task: TaskConfig, evaluator, row: dict
) -> RowOutcome:
    """Run one agentic loop for a row; the loop replaces the attempt budget."""
    loop = await run_loop(client, task, row)
    verdict = await assess(task, evaluator, loop.output, row)
    if verdict.judge_meta is not None:
        loop.meta["judge_meta"] = verdict.judge_meta

    outcome = _outcome(row, verdict, attempts=1, metas=[loop.meta])
    outcome.loop = loop
    return outcome


async def _process_row(client: ModelClient, task: TaskConfig, evaluator, row: dict) -> RowOutcome:
    """Generate one solution for a row, retrying under rejection until it passes."""
    messages = build_messages(task.prompt, row)
    is_rejection = task.generation.scheme == "rejection"
    metas: list[dict] = []
    verdict = Verdict(passed=False)

    for attempt in range(1, task.generation.legacy_attempts + 1):
        completion = await client.complete(messages)
        if completion is None:
            return _outcome(row, Verdict(passed=False), attempt, metas)

        metas.append(completion.meta)
        verdict = await assess(task, evaluator, completion.text, row)
        if verdict.judge_meta is not None:
            completion.meta["judge_meta"] = verdict.judge_meta
        if verdict.passed is not False or not is_rejection:
            return _outcome(row, verdict, attempt, metas)

    return _outcome(row, _exhausted(verdict), task.generation.legacy_attempts, metas)


def _exhausted(verdict: Verdict) -> Verdict:
    """A rejection row that kept nothing, still reporting why it was rejected."""
    return Verdict(
        passed=False, schema_valid=verdict.schema_valid, schema_error=verdict.schema_error
    )


def _outcome(row: dict, verdict: Verdict, attempts: int, metas: list[dict]) -> RowOutcome:
    return RowOutcome(
        row=row,
        output=verdict.value,
        passed=verdict.passed,
        extracted_answer=verdict.extracted,
        attempts=attempts,
        judge_score=verdict.judge_score,
        metas=metas,
        schema_valid=verdict.schema_valid,
        schema_error=verdict.schema_error,
    )
