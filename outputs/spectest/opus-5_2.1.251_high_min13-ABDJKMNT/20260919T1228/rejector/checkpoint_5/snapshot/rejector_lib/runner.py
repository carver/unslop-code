"""Executes the generation schemes for each task across all of its rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

from .agentic import AgenticRun, run_loop
from .api import ChatClient, Channel, Endpoint, Usage
from .config import TaskConfig
from .cost import BudgetStop, CostRates
from .evaluation import Verdict
from .inputs import render_messages
from .limits import RateLimiter
from .progress import ProgressReporter
from .scoring import NO_EVALUATION, attempt_meta, failure_verdict, score_response
from .solutions import MultiOutcome, collect_solutions

ENDPOINT_PATHS = {"chat": "/v1/chat/completions", "completions": "/v1/completions"}


@dataclass
class RowOutcome:
    """What one input row produced, before it is shaped into output JSON."""

    verdict: Verdict
    attempts: int
    metas: list[dict] = field(default_factory=list)
    iterations: int | None = None
    tool_calls: list[dict] | None = None

    @property
    def output(self):
        """What the row writes under its `output_field`."""
        return self.verdict.output

    @property
    def solution_count(self) -> int:
        return 0 if self.output is None else 1

    @property
    def row_passed(self) -> bool:
        """Passed, or unscored but answered, as in Part 1's summary counts."""
        passed = self.verdict.passed
        return passed is True or (passed is None and self.output is not None)


@dataclass(frozen=True)
class TaskResult:
    """Everything a finished task contributes to its output file and the summary."""

    task: TaskConfig
    rows: list[dict]
    outcomes: list[RowOutcome | MultiOutcome]
    usage: Usage


def open_channel(task: TaskConfig, client: ChatClient) -> Channel:
    """The endpoints one task's generation and judge calls share."""
    generation = Endpoint(
        url=f"{task.api_url}{ENDPOINT_PATHS[task.api_type]}",
        model=task.model,
        max_tokens=task.generation.max_tokens,
        limiter=RateLimiter(task.limits),
        usage=Usage(),
        rates=task.cost or CostRates(),
        api_type=task.api_type,
        chat_template=task.chat_template,
    )
    judge = None
    if task.judge_model is not None:
        judge = replace(generation, model=task.judge_model)
    return Channel(client=client, generation=generation, judge=judge)


async def run_task(
    task: TaskConfig,
    rows: list[dict],
    client: ChatClient,
    progress: ProgressReporter,
) -> TaskResult:
    """Process every row of one task concurrently, in input order.

    Rows the budget stopped are dropped rather than half-written, so the
    result holds the rows that actually finished, still in input order.
    """
    channel = open_channel(task, client)
    running = [
        asyncio.create_task(_process_row(row, task, channel, progress)) for row in rows
    ]
    outcomes = await asyncio.gather(*running)
    finished = [(row, outcome) for row, outcome in zip(rows, outcomes) if outcome]
    return TaskResult(
        task,
        [row for row, _ in finished],
        [outcome for _, outcome in finished],
        channel.generation.usage,
    )


async def _process_row(
    row: dict, task: TaskConfig, channel: Channel, progress: ProgressReporter
):
    """One row, or None once the budget stopped it before it could finish."""
    try:
        outcome = await _run_row(row, task, channel)
    except BudgetStop:
        return None
    progress.row_done(outcome.row_passed)
    return outcome


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
        return RowOutcome(failure_verdict(task), attempts=1)

    verdict = await score_response(completion.content, task, row, channel)
    return RowOutcome(verdict, 1, [attempt_meta(completion, verdict, task)])


async def _run_agentic(row: dict, task: TaskConfig, channel: Channel) -> RowOutcome:
    """One agentic loop, reported in the Part 1 single-row shape."""
    run = await run_loop(row, task, channel)
    verdict = (
        failure_verdict(task)
        if run.content is None
        else await score_response(run.content, task, row, channel)
    )
    return RowOutcome(verdict, 1, _agentic_metas(run), run.iterations, run.tool_calls)


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
            return RowOutcome(failure_verdict(task), attempt, metas)

        verdict = await score_response(completion.content, task, row, channel)
        metas.append(attempt_meta(completion, verdict, task))
        if verdict.passed:
            return RowOutcome(verdict, attempt, metas)
    # Out of attempts: the row keeps the last verdict's judge and schema
    # detail, but reports no output of its own.
    exhausted = replace(verdict, passed=False, output=None, extracted_answer=None)
    return RowOutcome(exhausted, task.generation.n, metas)
