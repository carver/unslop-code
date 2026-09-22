"""Concurrent execution of a task over the input rows.

Rows are handed to a pool of workers in input order, so requests go out in
input order while many stay in flight; each worker keeps its own row's
response, which is what preserves the input/output pairing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

import aiohttp

from .api import ChatClient
from .config import TaskConfig
from .generation import RowOutcome, generate_row

# Upper bound on simultaneous connections, so a huge rpm cannot exhaust
# sockets on the client side.
MAX_CONCURRENCY = 256


def concurrency_for(rpm: int, row_count: int) -> int:
    """In-flight requests needed to keep a server of capacity `rpm` busy."""
    return max(1, min(rpm, MAX_CONCURRENCY, row_count))


async def execute(
    config: TaskConfig, rows: Sequence[Mapping[str, Any]]
) -> tuple[list[RowOutcome], float]:
    """Run every row and return its outcome plus the first-to-last elapsed time."""
    if not rows:
        return [], 0.0

    workers = concurrency_for(config.rpm, len(rows))
    connector = aiohttp.TCPConnector(limit=workers)
    async with aiohttp.ClientSession(connector=connector) as session:
        client = ChatClient(
            session, config.api_url, config.model, config.generation.max_tokens
        )
        outcomes = await _process_rows(client, config, rows, workers)
        return outcomes, client.window.elapsed


async def _process_rows(
    client: ChatClient,
    config: TaskConfig,
    rows: Sequence[Mapping[str, Any]],
    workers: int,
) -> list[RowOutcome]:
    pending: asyncio.Queue[int] = asyncio.Queue()
    for index in range(len(rows)):
        pending.put_nowait(index)
    outcomes: list[RowOutcome | None] = [None] * len(rows)

    async def worker() -> None:
        while not pending.empty():
            index = pending.get_nowait()
            outcomes[index] = await generate_row(client, config, rows[index])

    await asyncio.gather(*(worker() for _ in range(workers)))
    return outcomes
