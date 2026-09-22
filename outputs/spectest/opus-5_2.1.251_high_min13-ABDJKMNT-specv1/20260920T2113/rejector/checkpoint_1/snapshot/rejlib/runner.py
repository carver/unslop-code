"""Orchestration: fan rows out concurrently, then assemble output and summary."""

from __future__ import annotations

import asyncio

import httpx

from rejlib.api import ChatClient, Stats
from rejlib.config import TaskConfig
from rejlib.ratelimit import RateLimiter
from rejlib.schemes import Outcome, generate

MIN_IN_FLIGHT = 8
MAX_IN_FLIGHT = 256
TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=300.0)


def in_flight_limit(rpm: int) -> int:
    """How many rows may be in flight: one minute of budget, clamped (T1)."""
    return max(MIN_IN_FLIGHT, min(rpm, MAX_IN_FLIGHT))


async def process_rows(config: TaskConfig, rows: list[dict]) -> tuple[list[dict], Stats]:
    """Process every row concurrently and return the output rows in input order."""
    stats = Stats()
    limiter = RateLimiter(config.rpm)
    capacity = in_flight_limit(config.rpm)
    results: list[dict | None] = [None] * len(rows)
    semaphore = asyncio.Semaphore(capacity)
    limits = httpx.Limits(max_connections=capacity, max_keepalive_connections=capacity)

    async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as http:
        client = ChatClient(http, config, limiter, stats)
        tasks = []
        # Tasks are created in input order and each one's first action is to take a
        # rate-limiter token, so requests also leave in input order.
        for index, row in enumerate(rows):
            await semaphore.acquire()
            tasks.append(asyncio.create_task(
                _process_row(client, config, row, index, results, semaphore)
            ))
        await asyncio.gather(*tasks)
    return results, stats


async def _process_row(client: ChatClient, config: TaskConfig, row: dict, index: int,
                       results: list, semaphore: asyncio.Semaphore) -> None:
    try:
        outcome = await generate(client, config, row)
    finally:
        semaphore.release()
    results[index] = output_row(config, row, outcome)


def output_row(config: TaskConfig, row: dict, outcome: Outcome) -> dict:
    """Assemble one output record from a row's generation outcome."""
    return {
        "input": row,
        "output": None if outcome.content is None else {config.output_field: outcome.content},
        "result": {
            "passed": outcome.passed,
            "extracted_answer": outcome.extracted,
            "attempts": outcome.attempts,
        },
        # A single object for one-attempt rows, a list per attempt otherwise (T14).
        "meta": outcome.metas[0] if len(outcome.metas) == 1 else outcome.metas,
    }


def build_summary(results: list[dict], stats: Stats) -> dict:
    """The one-line JSON summary printed after processing finishes."""
    passed = sum(1 for result in results if _counts_as_passed(result))
    elapsed = stats.elapsed
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.api_calls / elapsed * 60, 1) if elapsed > 0 else 0.0,
    }


def _counts_as_passed(result: dict) -> bool:
    """Passing evaluation, or - with no evaluation configured - any produced output."""
    passed = result["result"]["passed"]
    return passed is True or (passed is None and result["output"] is not None)
