"""Concurrent execution of a task over the input rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from .api import ApiStats, ChatClient
from .config import TaskConfig
from .evaluation import Evaluator
from .prompts import build_messages

MAX_IN_FLIGHT = 256


@dataclass
class RowOutcome:
    """What one input row produced."""

    row: dict
    output: str | None
    passed: bool | None
    extracted_answer: str | None
    attempts: int
    metas: list[dict] = field(default_factory=list)


def run_task(task: TaskConfig, rows: list[dict]) -> tuple[list[RowOutcome], ApiStats]:
    """Process every row, preserving input order."""
    return asyncio.run(_run(task, rows))


async def _run(task: TaskConfig, rows: list[dict]) -> tuple[list[RowOutcome], ApiStats]:
    in_flight = _in_flight_limit(task.rpm, len(rows))
    limits = httpx.Limits(max_connections=in_flight, max_keepalive_connections=in_flight)
    evaluator = Evaluator(task.evaluation) if task.evaluation else None
    slots = asyncio.Semaphore(in_flight)

    async with httpx.AsyncClient(limits=limits, timeout=120.0) as http:
        client = ChatClient(http, task)

        async def process(row: dict) -> RowOutcome:
            async with slots:
                return await _process_row(client, task, evaluator, row)

        outcomes = await asyncio.gather(*(process(row) for row in rows))
    return list(outcomes), client.stats


def _in_flight_limit(rpm: int, row_count: int) -> int:
    """Concurrency budget: enough to saturate a server rated at `rpm`.

    The server queues internally and never rate-limits, so the only cost of a
    deep pipeline is memory; capacity equal to `rpm` keeps at most a minute of
    work queued while leaving no slot idle.
    """
    return max(1, min(rpm, MAX_IN_FLIGHT, row_count or 1))


async def _process_row(
    client: ChatClient, task: TaskConfig, evaluator: Evaluator | None, row: dict
) -> RowOutcome:
    """Generate for one row, retrying under rejection until something passes."""
    messages = build_messages(task, row)
    is_rejection = task.generation.scheme == "rejection"
    metas: list[dict] = []

    for attempt in range(1, task.generation.max_attempts + 1):
        completion = await client.complete(messages)
        if completion is None:
            return RowOutcome(row, None, False, None, attempt, metas)

        metas.append(completion.meta)
        passed, extracted = evaluator.evaluate(completion.text, row) if evaluator else (None, None)
        if passed is not False or not is_rejection:
            return RowOutcome(row, completion.text, passed, extracted, attempt, metas)

    return RowOutcome(row, None, False, None, task.generation.max_attempts, metas)
