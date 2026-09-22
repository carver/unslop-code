"""Executes the generation schemes for each task across all of its rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

from .agentic import AgenticRun, run_loop
from .api import ChatClient, Channel, Endpoint, Usage
from .config import TaskConfig
from .inputs import render_messages
from .scoring import NO_EVALUATION, attempt_meta, failure_verdict, score_response
from .solutions import MultiOutcome, collect_solutions

MAX_IN_FLIGHT = 256
ENDPOINT_PATHS = {"chat": "/v1/chat/completions", "completions": "/v1/completions"}


@dataclass
class RowOutcome:
    """What one input row produced, before it is shaped into output JSON."""

    content: str | None
    passed: bool | None
    extracted_answer: str | None
    attempts: int
    metas: list[dict] = field(default_factory=list)
    judge_score: float | None = None
    iterations: int | None = None
    tool_calls: list[dict] | None = None

    @property
    def solution_count(self) -> int:
        return 0 if self.content is None else 1

    @property
    def row_passed(self) -> bool:
        """Passed, or unevaluated but answered, as in Part 1's summary counts."""
        return self.passed is True or (self.passed is None and self.content is not None)


@dataclass(frozen=True)
class TaskResult:
    """Everything a finished task contributes to its output file and the summary."""

    task: TaskConfig
    rows: list[dict]
    outcomes: list[RowOutcome | MultiOutcome]
    usage: Usage


def in_flight_limit(rpm: int) -> int:
    """How many requests to keep in flight for a server with this capacity.

    The server queues internally and never rate-limits, so the client aims to
    keep a minute's worth of its budget outstanding rather than pacing itself.
    """
    return max(1, min(rpm, MAX_IN_FLIGHT))


def open_channel(task: TaskConfig, client: ChatClient) -> Channel:
    """The endpoints one task's generation and judge calls share."""
    generation = Endpoint(
        url=f"{task.api_url}{ENDPOINT_PATHS[task.api_type]}",
        model=task.model,
        max_tokens=task.generation.max_tokens,
        slots=asyncio.Semaphore(in_flight_limit(task.rpm)),
        usage=Usage(),
        api_type=task.api_type,
        chat_template=task.chat_template,
    )
    judge = None
    if task.judge_model is not None:
        judge = replace(generation, model=task.judge_model)
    return Channel(client=client, generation=generation, judge=judge)


async def run_task(
    task: TaskConfig, rows: list[dict], client: ChatClient
) -> TaskResult:
    """Process every row of one task concurrently, in input order."""
    channel = open_channel(task, client)
    running = [asyncio.create_task(_run_row(row, task, channel)) for row in rows]
    outcomes = list(await asyncio.gather(*running))
    return TaskResult(task, rows, outcomes, channel.generation.usage)


async def _run_row(row: dict, task: TaskConfig, channel: Channel):
    """One row, either as a list of solutions or in the Part 1 single-shot shape."""
    if task.list_format:
        return await collect_solutions(row, task, channel)
    if task.is_agentic:
        return await _run_agentic(row, task, channel)

    messages = render_messages(row, task)
    temperature = task.generation.temperature
    if task.generation.scheme == "rejection":
        return await _run_rejection(messages, temperature, row, task, channel)

    completion = await channel.client.complete(messages, temperature, channel.generation)
    if completion is None:
        return RowOutcome(None, failure_verdict(task).passed, None, attempts=1)

    verdict = await score_response(completion.content, task, row, channel)
    return RowOutcome(
        completion.content,
        verdict.passed,
        verdict.extracted_answer,
        1,
        [attempt_meta(completion, verdict, task)],
        verdict.judge_score,
    )


async def _run_agentic(row: dict, task: TaskConfig, channel: Channel) -> RowOutcome:
    """One agentic loop, reported in the Part 1 single-row shape."""
    run = await run_loop(row, task, channel)
    verdict = (
        failure_verdict(task)
        if run.content is None
        else await score_response(run.content, task, row, channel)
    )
    return RowOutcome(
        run.content,
        verdict.passed,
        verdict.extracted_answer,
        1,
        _agentic_metas(run),
        verdict.judge_score,
        run.iterations,
        run.tool_calls,
    )


def _agentic_metas(run: AgenticRun) -> list[dict]:
    """A loop that never got a response leaves no metadata, as in Part 1."""
    return [run.meta] if run.iterations else []


async def _run_rejection(
    messages: list[dict],
    temperature: float,
    row: dict,
    task: TaskConfig,
    channel: Channel,
) -> RowOutcome:
    """Sample up to `n` times, keeping the first response that passes."""
    metas: list[dict] = []
    verdict = NO_EVALUATION
    for attempt in range(1, task.generation.n + 1):
        completion = await channel.client.complete(
            messages, temperature, channel.generation
        )
        if completion is None:
            return RowOutcome(None, False, None, attempt, metas)

        verdict = await score_response(completion.content, task, row, channel)
        metas.append(attempt_meta(completion, verdict, task))
        if verdict.passed:
            return RowOutcome(
                completion.content,
                True,
                verdict.extracted_answer,
                attempt,
                metas,
                verdict.judge_score,
            )
    return RowOutcome(None, False, None, task.generation.n, metas, verdict.judge_score)
