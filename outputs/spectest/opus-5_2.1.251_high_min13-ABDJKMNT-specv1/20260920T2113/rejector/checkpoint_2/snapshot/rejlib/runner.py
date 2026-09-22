"""Orchestration: run every selected task concurrently, then build the summary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from rejlib.api import ChatClient, Stats
from rejlib.config import TaskConfig
from rejlib.evaluation import Evaluator, build_evaluator
from rejlib.ratelimit import RateLimiter
from rejlib.schemes import Outcome, generate

MIN_IN_FLIGHT = 8
MAX_IN_FLIGHT = 256
TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=300.0)


@dataclass
class TaskRun:
    """One task's output rows, in input order, and the counters it produced."""

    rows: list[dict]
    stats: Stats


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


def output_row(config: TaskConfig, row: dict, outcome: Outcome) -> dict:
    """Assemble one output record from a row's generation outcome."""
    result = {
        "passed": outcome.passed,
        "extracted_answer": outcome.extracted,
        "attempts": outcome.attempts,
    }
    if config.evaluation and config.evaluation.type == "llm_judge":
        result["judge_score"] = outcome.judge_score  # judged rows only (T28)
    return {
        "input": row,
        "output": None if outcome.content is None else {config.output_field: outcome.content},
        "result": result,
        # A single object for one-attempt rows, a list per attempt otherwise (T14).
        "meta": outcome.metas[0] if len(outcome.metas) == 1 else outcome.metas,
    }


def build_summary(runs: dict[str, TaskRun], multi: bool) -> dict:
    """The one-line JSON summary printed after processing finishes."""
    stats = Stats.merged(run.stats for run in runs.values())
    rows = [row for run in runs.values() for row in run.rows]
    elapsed = stats.elapsed
    summary = {
        **_counts(rows),
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.api_calls / elapsed * 60, 1) if elapsed > 0 else 0.0,
    }
    if multi:
        summary["tasks"] = {
            name: {**_counts(run.rows), "total_api_calls": run.stats.api_calls}
            for name, run in runs.items()
        }
    return summary


def _counts(rows: list[dict]) -> dict:
    """Row counts over one task's rows, or over every row that ran."""
    passed = sum(1 for row in rows if _counts_as_passed(row))
    return {"total": len(rows), "passed": passed, "failed": len(rows) - passed}


def _counts_as_passed(result: dict) -> bool:
    """Passing evaluation, or - with no evaluation configured - any produced output."""
    passed = result["result"]["passed"]
    return passed is True or (passed is None and result["output"] is not None)
