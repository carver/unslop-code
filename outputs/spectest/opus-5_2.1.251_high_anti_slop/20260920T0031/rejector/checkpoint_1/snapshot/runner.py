"""Concurrent execution of a task over its input rows, plus the run summary."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import httpx

from api import REQUEST_TIMEOUT_SECONDS, ChatClient, Completion, RateLimiter
from config import TaskConfig
from dataset import Message
from evaluation import NO_EVALUATION, Outcome, evaluate

Row = dict[str, Any]
Result = dict[str, Any]


async def run_task(
    task: TaskConfig, rows: Sequence[Row], prompts: Sequence[list[Message]]
) -> tuple[list[Result], dict[str, Any]]:
    """Process every row concurrently and return the result rows and the run summary."""
    # A full minute of the request budget may be in flight at once; the limiter paces the rest.
    in_flight = task.rpm
    async with httpx.AsyncClient(
        base_url=task.api_url, timeout=REQUEST_TIMEOUT_SECONDS, limits=httpx.Limits(max_connections=in_flight)
    ) as http:
        client = ChatClient(http, task.model, RateLimiter(task.rpm))
        semaphore = asyncio.Semaphore(in_flight)

        async def run_row(row: Row, messages: list[Message]) -> Result:
            async with semaphore:
                return await process_row(task, client, row, messages)

        results = await asyncio.gather(*(run_row(row, messages) for row, messages in zip(rows, prompts, strict=True)))

    return list(results), summarize(results, client.api_calls, client.elapsed_seconds)


async def process_row(task: TaskConfig, client: ChatClient, row: Row, messages: list[Message]) -> Result:
    """Generate for one row, resampling while rejection sampling has attempts left."""
    generation = task.generation
    metas: list[dict[str, Any]] = []
    completion: Completion | None = None
    outcome = NO_EVALUATION

    for _ in range(generation.attempts):
        completion = await client.complete(messages, generation.temperature, generation.max_tokens)
        if completion is None:
            break
        metas.append(completion.meta)
        outcome = evaluate(completion.text, row, task.evaluation)
        if outcome.passed is not False:
            break

    return _result_row(task, row, completion, outcome, metas)


def _result_row(
    task: TaskConfig, row: Row, completion: Completion | None, outcome: Outcome, metas: list[dict[str, Any]]
) -> Result:
    rejected = task.generation.scheme == "rejection" and outcome.passed is False
    output = None if completion is None or rejected else {task.output_field: completion.text}
    return {
        "input": row,
        "output": output,
        "result": {
            "passed": None if task.evaluation is None else (outcome.passed is True and output is not None),
            "extracted_answer": outcome.extracted if output is not None else None,
            "attempts": max(len(metas), 1),
        },
        "meta": _meta_field(metas),
    }


def _meta_field(metas: list[dict[str, Any]]) -> Any:
    """A single metadata object for one-attempt rows, a list for multi-attempt ones."""
    if len(metas) == 1:
        return metas[0]
    return metas or None


def _row_metas(result: Result) -> list[dict[str, Any]]:
    meta = result["meta"]
    if isinstance(meta, list):
        return meta
    return [meta] if meta else []


def _row_passed(result: Result) -> bool:
    """Rows without a configured evaluation count as passed when the API answered."""
    passed = result["result"]["passed"]
    return passed is True or (passed is None and result["output"] is not None)


def summarize(results: Sequence[Result], api_calls: int, elapsed_seconds: float) -> dict[str, Any]:
    """Aggregate per-row results and client counters into the stdout summary object."""
    metas = [meta for result in results for meta in _row_metas(result)]
    return {
        "total": len(results),
        "passed": sum(1 for result in results if _row_passed(result)),
        "failed": sum(1 for result in results if not _row_passed(result)),
        "total_prompt_tokens": sum(meta["prompt_tokens"] for meta in metas),
        "total_completion_tokens": sum(meta["completion_tokens"] for meta in metas),
        "total_api_calls": api_calls,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "throughput_rpm": round(api_calls / elapsed_seconds * 60, 1) if elapsed_seconds else 0.0,
    }
