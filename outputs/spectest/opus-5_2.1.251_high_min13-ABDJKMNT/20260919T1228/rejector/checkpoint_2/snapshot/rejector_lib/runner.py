"""Executes the generation schemes for each task across all of its rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

from .api import ChatClient, Channel, Completion, Endpoint, Usage
from .config import TaskConfig
from .evaluation import Verdict, evaluate_response
from .inputs import render_messages
from .judge import judge_response
from .script_eval import run_script

MAX_IN_FLIGHT = 256
NO_EVALUATION = Verdict(passed=None)


@dataclass
class RowOutcome:
    """What one input row produced, before it is shaped into output JSON."""

    content: str | None
    passed: bool | None
    extracted_answer: str | None
    attempts: int
    metas: list[dict] = field(default_factory=list)
    judge_score: float | None = None


@dataclass(frozen=True)
class TaskResult:
    """Everything a finished task contributes to its output file and the summary."""

    task: TaskConfig
    rows: list[dict]
    outcomes: list[RowOutcome]
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
        url=f"{task.api_url}/v1/chat/completions",
        model=task.model,
        max_tokens=task.generation.max_tokens,
        slots=asyncio.Semaphore(in_flight_limit(task.rpm)),
        usage=Usage(),
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


async def _run_row(row: dict, task: TaskConfig, channel: Channel) -> RowOutcome:
    messages = render_messages(row, task)
    temperature = task.generation.temperature
    if task.generation.scheme == "rejection":
        return await _run_rejection(messages, temperature, row, task, channel)

    completion = await channel.client.complete(messages, temperature, channel.generation)
    if completion is None:
        return RowOutcome(None, _failure_verdict(task), None, attempts=1)

    verdict = await _score(completion.content, task, row, channel)
    return RowOutcome(
        completion.content,
        verdict.passed,
        verdict.extracted_answer,
        1,
        [_meta(completion, verdict, task)],
        verdict.judge_score,
    )


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

        verdict = await _score(completion.content, task, row, channel)
        metas.append(_meta(completion, verdict, task))
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


async def _score(
    text: str, task: TaskConfig, row: dict, channel: Channel
) -> Verdict:
    """Evaluate one response with whichever evaluation the task configures."""
    evaluation = task.evaluation
    if evaluation is None:
        return NO_EVALUATION
    if evaluation.type == "script":
        return Verdict(passed=await run_script(evaluation.script, row, text))
    if evaluation.type == "llm_judge":
        return await judge_response(text, evaluation, row, channel)

    passed, extracted = evaluate_response(text, evaluation, row)
    return Verdict(passed=passed, extracted_answer=extracted)


def _meta(completion: Completion, verdict: Verdict, task: TaskConfig) -> dict:
    """One attempt's metadata, carrying its judge call's metadata when judged."""
    if task.judge is None:
        return completion.meta
    return {**completion.meta, "judge_meta": verdict.judge_meta}


def _failure_verdict(task: TaskConfig) -> bool | None:
    """A row with no usable response fails, unless nothing was being evaluated."""
    return None if task.evaluation is None else False
