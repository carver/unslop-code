"""Executes the generation schemes across all input rows concurrently."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .api import ChatClient
from .config import TaskConfig
from .evaluation import evaluate_response
from .inputs import render_messages

MAX_IN_FLIGHT = 256


@dataclass
class RowOutcome:
    """What one input row produced, before it is shaped into output JSON."""

    content: str | None
    passed: bool | None
    extracted_answer: str | None
    attempts: int
    metas: list[dict] = field(default_factory=list)


def in_flight_limit(rpm: int) -> int:
    """How many requests to keep in flight for a server with this capacity.

    The server queues internally and never rate-limits, so the client aims to
    keep a minute's worth of its budget outstanding rather than pacing itself.
    """
    return max(1, min(rpm, MAX_IN_FLIGHT))


async def run_rows(
    rows: list[dict], config: TaskConfig, client: ChatClient
) -> list[RowOutcome]:
    """Process every row concurrently, returning outcomes in input order."""
    tasks = [asyncio.create_task(_run_row(row, config, client)) for row in rows]
    return list(await asyncio.gather(*tasks))


async def _run_row(row: dict, config: TaskConfig, client: ChatClient) -> RowOutcome:
    messages = render_messages(row, config)
    temperature = config.generation.temperature
    if config.generation.scheme == "rejection":
        return await _run_rejection(messages, temperature, row, config, client)

    completion = await client.complete(messages, temperature)
    if completion is None:
        return RowOutcome(None, _failure_verdict(config), None, attempts=1)
    passed, extracted = _score(completion.content, config, row)
    return RowOutcome(completion.content, passed, extracted, 1, [completion.meta])


async def _run_rejection(
    messages: list[dict],
    temperature: float,
    row: dict,
    config: TaskConfig,
    client: ChatClient,
) -> RowOutcome:
    """Sample up to `n` times, keeping the first response that passes."""
    metas: list[dict] = []
    for attempt in range(1, config.generation.n + 1):
        completion = await client.complete(messages, temperature)
        if completion is None:
            return RowOutcome(None, False, None, attempt, metas)
        metas.append(completion.meta)
        passed, extracted = _score(completion.content, config, row)
        if passed:
            return RowOutcome(completion.content, True, extracted, attempt, metas)
    return RowOutcome(None, False, None, config.generation.n, metas)


def _score(text: str, config: TaskConfig, row: dict) -> tuple[bool | None, str | None]:
    """Evaluate a response, or report (None, None) when no evaluation is set."""
    if config.evaluation is None:
        return None, None
    return evaluate_response(text, config.evaluation, row)


def _failure_verdict(config: TaskConfig) -> bool | None:
    """A row with no usable response fails, unless nothing was being evaluated."""
    return None if config.evaluation is None else False
