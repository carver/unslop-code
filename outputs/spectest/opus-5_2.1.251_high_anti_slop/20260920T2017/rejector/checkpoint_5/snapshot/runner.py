"""Concurrent execution of the selected tasks over their input rows."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, replace
from itertools import takewhile
from typing import Any, Awaitable, Iterable

from agentic import Generation, run_agentic
from client import ApiClient, ClientStats, combine_stats, open_clients
from config import TaskConfig
from cost import BudgetExhausted, CostTracker
from icl import IclPlan, PreparedSetup
from jobs import TaskJob
from progress import ProgressReporter
from prompts import RenderedPrompt
from records import (
    Attempt,
    MultiOutcome,
    RowOutcome,
    counts,
    multi_record,
    single_record,
)
from schema import check_output
from verdicts import Verdict, evaluate_response


@dataclass(frozen=True)
class TaskResult:
    """One task's records in input order, with the counters its calls ran up.

    `resumed_from` is the number of leading input rows an earlier run had
    already written, which these records follow.
    """

    name: str
    records: list[dict[str, Any]]
    stats: ClientStats
    resumed_from: int


async def run_tasks(
    jobs: list[TaskJob], cost: CostTracker, show_progress: bool = False
) -> list[TaskResult]:
    """Process every task concurrently and return their results in job order.

    Rows within a task, and the tasks themselves, are all in flight at once;
    each task's requests are paced by its own rate limits, so the work of
    different tasks interleaves freely.
    """
    async with open_clients([job.config for job in jobs], cost) as clients:
        progress = ProgressReporter(
            total=sum(len(job.rows) for job in jobs),
            stats=[client.stats for client in clients],
            cost=cost,
            verdicts=any(job.config.evaluation or job.config.output_schema for job in jobs),
            stream=sys.stderr if show_progress else None,
        )
        records = await asyncio.gather(
            *(_run_job(client, job, progress) for client, job in zip(clients, jobs))
        )
    return [
        TaskResult(job.config.name, job_records, client.stats, job.resumed_from)
        for job, job_records, client in zip(jobs, records, clients)
    ]


async def _run_job(
    client: ApiClient, job: TaskJob, progress: ProgressReporter
) -> list[dict[str, Any]]:
    """Run every row of one task, keeping the rows the run got all the way through.

    A budget that runs out mid-run leaves later rows unfinished; only the
    leading run of finished rows is written, so the file stays in input order
    and a `--resume` run can pick up exactly where this one stopped.
    """
    records = await asyncio.gather(
        *(
            _run_row(client, job, prompt, row, progress)
            for prompt, row in zip(job.prompts, job.rows)
        )
    )
    return list(takewhile(lambda record: record is not None, records))


async def _run_row(
    client: ApiClient,
    job: TaskJob,
    prompt: RenderedPrompt,
    row: dict[str, Any],
    progress: ProgressReporter,
) -> dict[str, Any] | None:
    """Run one row to a record, or to None if the budget stopped it first."""
    try:
        record = await _row_record(client, job, prompt, row)
    except BudgetExhausted:
        return None
    progress.record(record)
    return record


async def _row_record(
    client: ApiClient, job: TaskJob, prompt: RenderedPrompt, row: dict[str, Any]
) -> dict[str, Any]:
    """Generate one row's solutions and shape them into its output record."""
    config = job.config
    if not config.list_output:
        return single_record(config, row, await _generate_one(client, config, prompt, row))
    collect = _collect_passing if config.generation.scheme == "rejection" else _collect_every
    return multi_record(config, row, await collect(client, job, prompt, row))


async def _generate_one(
    client: ApiClient, config: TaskConfig, prompt: RenderedPrompt, row: dict[str, Any]
) -> RowOutcome:
    """A row of a single-solution task without ICL: one solution, or none."""
    if config.generation.scheme == "rejection":
        return await _run_rejection(client, config, prompt, row)

    attempt = await _attempt(client, config, prompt, row, None)
    if attempt is None:
        return _failed_outcome(config, attempts=1, metas=[])
    return RowOutcome(
        attempt.output, attempt.verdict, 1, [attempt.meta], attempt.iterations, attempt.tool_calls
    )


async def _run_rejection(
    client: ApiClient, config: TaskConfig, prompt: RenderedPrompt, row: dict[str, Any]
) -> RowOutcome:
    """Sample until a response is accepted or the budget of attempts runs out."""
    metas: list[dict[str, Any]] = []
    for number in range(1, config.generation.n + 1):
        attempt = await _attempt(client, config, prompt, row, None)
        if attempt is None:
            continue
        metas.append(attempt.meta)
        if attempt.verdict.passed:
            return RowOutcome(attempt.output, attempt.verdict, number, metas)
    return _failed_outcome(config, attempts=config.generation.n, metas=metas)


async def _collect_every(
    client: ApiClient, job: TaskJob, prompt: RenderedPrompt, row: dict[str, Any]
) -> MultiOutcome:
    """Make one request per planned attempt; the evaluation gates none of them."""
    setups = _attempt_setups(job.config, job.icl)
    attempts = await _together(
        _attempt(client, job.config, prompt, row, setup) for setup in setups
    )
    answered = [attempt for attempt in attempts if attempt is not None]
    return MultiOutcome(
        solutions=[attempt for attempt in answered if attempt.output is not None],
        completed=answered,
        attempts=len(setups),
    )


async def _collect_passing(
    client: ApiClient, job: TaskJob, prompt: RenderedPrompt, row: dict[str, Any]
) -> MultiOutcome:
    """Sample until enough responses are accepted, or the budget is spent."""
    config = job.config
    solutions: list[Attempt] = []
    completed: list[Attempt] = []
    attempts = 0
    while len(solutions) < config.num_solutions and attempts < config.generation.max_attempts:
        attempt = await _attempt(client, config, prompt, row, job.icl.choose(attempts))
        attempts += 1
        if attempt is None:
            continue
        completed.append(attempt)
        if attempt.verdict.passed:
            solutions.append(attempt)
    return MultiOutcome(solutions=solutions, completed=completed, attempts=attempts)


async def _together(attempts: Iterable[Awaitable[Attempt | None]]) -> list[Attempt | None]:
    """Run a row's attempts at the same time, letting them all settle first.

    A budget stop ends the row, but only once its siblings have finished too, so
    no attempt is left running with nobody to read its result.
    """
    results = await asyncio.gather(*attempts, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


def _attempt_setups(config: TaskConfig, plan: IclPlan) -> list[PreparedSetup | None]:
    """The ICL setup of each attempt, one entry per attempt the row will make.

    Greedy has nothing to gain from repeating a setup — at temperature 0 it
    would only produce the same solution again — so once it wants several
    solutions it ignores the strategy, walks the setups in declared order, and
    stops when they run out. A single solution still follows the strategy.
    """
    if config.generation.scheme == "greedy" and config.num_solutions > 1:
        return list(plan.setups[: config.num_solutions]) or [None]
    return [plan.choose(index) for index in range(config.num_solutions)]


async def _attempt(
    client: ApiClient,
    config: TaskConfig,
    prompt: RenderedPrompt,
    row: dict[str, Any],
    setup: PreparedSetup | None,
) -> Attempt | None:
    """Generate one response and review it, or None if the API never answered."""
    if setup is not None:
        prompt = replace(prompt, examples=setup.turns)
    generated = await _generate(client, config, prompt)
    if generated is None:
        return None
    verdict, output = await _review(client, config, generated.text, row)
    meta = generated.meta
    if verdict.judge_meta is not None:
        meta = {**meta, "judge_meta": verdict.judge_meta}
    return Attempt(
        output=output,
        meta=meta,
        verdict=verdict,
        setup_name=setup.name if setup else None,
        iterations=generated.iterations,
        tool_calls=generated.tool_calls,
    )


async def _review(
    client: ApiClient, config: TaskConfig, text: str | None, row: dict[str, Any]
) -> tuple[Verdict, Any]:
    """Validate a response against the output schema, then evaluate it.

    Schema validation comes first and gates the evaluation: a response that is
    not valid JSON, or does not match the schema, is rejected without being
    judged and records nothing as its output. What a valid response records is
    the parsed JSON value, where a task without a schema records the raw text.
    """
    if config.output_schema is None or text is None:
        return await evaluate_response(config.evaluation, text, row, client), text

    check = check_output(config.output_schema, text)
    if check.error is not None:
        return Verdict(passed=False, schema_valid=False, schema_error=check.error), None
    verdict = await evaluate_response(config.evaluation, text, row, client)
    passed = verdict.passed if config.evaluation else True
    return replace(verdict, passed=passed, schema_valid=True), check.value


async def _generate(
    client: ApiClient, config: TaskConfig, prompt: RenderedPrompt
) -> Generation | None:
    """Run the task's scheme once: a whole agentic loop, or a single request.

    The unit of work holds one of the task's concurrency slots throughout, so an
    agentic loop keeps its slot across every iteration it makes.
    """
    generation = config.generation
    async with client.limiter.in_flight():
        if generation.scheme == "agentic":
            return await run_agentic(client, generation, config.tools, prompt)
        completion = await client.complete(
            prompt.messages(), generation.temperature, generation.max_tokens
        )
    return None if completion is None else Generation(completion.text, completion.meta)


def _failed_outcome(config: TaskConfig, attempts: int, metas: list[dict[str, Any]]) -> RowOutcome:
    """A row with no usable output; `passed` stays None when nothing judges it."""
    judged = config.evaluation or config.output_schema
    return RowOutcome(None, Verdict(passed=False if judged else None), attempts, metas)


def summarize(
    results: list[TaskResult], multi: bool, cost: CostTracker, resumed: bool = False
) -> dict[str, Any]:
    """Build the run summary printed to stdout.

    Rows with nothing to judge them count as passed as long as the API answered
    them. A resumed run counts only the rows it processed itself, and reports
    how many it skipped. A multi-task run also reports the same counts per task,
    including the API calls its judge made.
    """
    stats = combine_stats([result.stats for result in results])
    elapsed = stats.elapsed_seconds
    summary = {
        **counts([record for result in results for record in result.records]),
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.api_calls / elapsed * 60, 1) if elapsed else 0.0,
    }
    if resumed:
        summary["resumed_from"] = sum(result.resumed_from for result in results)
    if cost.configured:
        summary["cost"] = cost.summary()
    if multi:
        summary["tasks"] = {
            result.name: {**counts(result.records), "total_api_calls": result.stats.api_calls}
            for result in results
        }
    return summary
