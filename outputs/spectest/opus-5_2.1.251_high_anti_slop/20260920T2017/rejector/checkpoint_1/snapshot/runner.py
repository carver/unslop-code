"""Concurrent execution of a task over its input rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from client import ChatClient, ClientStats, open_client
from config import TaskConfig
from dataset import RenderedPrompt
from evaluation import evaluate


@dataclass(frozen=True)
class RowOutcome:
    """What a single input row produced, before it is shaped into a record."""

    output: str | None
    passed: bool | None
    extracted_answer: str | None
    attempts: int
    metas: list[dict[str, Any]]


async def run_task(
    config: TaskConfig, rows: list[dict[str, Any]], prompts: list[RenderedPrompt]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Process every row concurrently and return its records plus the summary.

    Rows are kept in input order; the concurrency comes from having many rows in
    flight at once, paced by the configured `rpm`.
    """
    async with open_client(config.api_url, config.model, config.rpm) as client:
        outcomes = await asyncio.gather(
            *(_run_row(client, config, prompt, row) for prompt, row in zip(prompts, rows))
        )

    records = [_to_record(config, row, outcome) for row, outcome in zip(rows, outcomes)]
    return records, summarize(records, client.stats)


async def _run_row(
    client: ChatClient, config: TaskConfig, prompt: RenderedPrompt, row: dict[str, Any]
) -> RowOutcome:
    generation = config.generation
    if generation.scheme == "rejection":
        return await _run_rejection(client, config, prompt, row)

    completion = await client.complete(prompt, generation.temperature, generation.max_tokens)
    if completion is None:
        return _failed_outcome(config, attempts=1, metas=[])
    passed, extracted = evaluate(config.evaluation, completion.text, row)
    return RowOutcome(completion.text, passed, extracted, 1, [completion.meta])


async def _run_rejection(
    client: ChatClient, config: TaskConfig, prompt: RenderedPrompt, row: dict[str, Any]
) -> RowOutcome:
    """Sample until a response passes the evaluation or the budget runs out."""
    generation = config.generation
    metas: list[dict[str, Any]] = []
    for attempt in range(1, generation.n + 1):
        completion = await client.complete(prompt, generation.temperature, generation.max_tokens)
        if completion is None:
            continue
        metas.append(completion.meta)
        passed, extracted = evaluate(config.evaluation, completion.text, row)
        if passed:
            return RowOutcome(completion.text, True, extracted, attempt, metas)
    return _failed_outcome(config, attempts=generation.n, metas=metas)


def _failed_outcome(config: TaskConfig, attempts: int, metas: list[dict[str, Any]]) -> RowOutcome:
    """A row with no usable output; `passed` stays None when nothing judges it."""
    passed = False if config.evaluation else None
    return RowOutcome(None, passed, None, attempts, metas)


def _to_record(config: TaskConfig, row: dict[str, Any], outcome: RowOutcome) -> dict[str, Any]:
    # One metadata object for single-attempt rows, a list once rejection sampling
    # made several attempts, and null when no attempt reached the API.
    metas = outcome.metas
    return {
        "input": row,
        "output": None if outcome.output is None else {config.output_field: outcome.output},
        "result": {
            "passed": outcome.passed,
            "extracted_answer": outcome.extracted_answer,
            "attempts": outcome.attempts,
        },
        "meta": metas[0] if len(metas) == 1 else (metas or None),
    }


def summarize(records: list[dict[str, Any]], stats: ClientStats) -> dict[str, Any]:
    """Build the run summary printed to stdout.

    Rows with no evaluation configured count as passed as long as the API
    answered them.
    """
    elapsed = stats.elapsed_seconds
    passed = sum(1 for record in records if _is_passed(record))
    return {
        "total": len(records),
        "passed": passed,
        "failed": len(records) - passed,
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.api_calls / elapsed * 60, 1) if elapsed else 0.0,
    }


def _is_passed(record: dict[str, Any]) -> bool:
    passed = record["result"]["passed"]
    return passed is True or (passed is None and record["output"] is not None)
