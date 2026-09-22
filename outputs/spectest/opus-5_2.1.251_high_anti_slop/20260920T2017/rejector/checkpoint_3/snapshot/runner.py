"""Concurrent execution of the selected tasks over their input rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

from client import ChatClient, ClientStats, combine_stats, open_clients
from config import TaskConfig
from icl import IclPlan, PreparedSetup
from jobs import TaskJob
from prompts import RenderedPrompt
from verdicts import Verdict, evaluate_response


@dataclass(frozen=True)
class Attempt:
    """One generated response, with the metadata, verdict and setup behind it."""

    text: str
    meta: dict[str, Any]
    verdict: Verdict
    setup_name: str | None


@dataclass(frozen=True)
class RowOutcome:
    """What a single-solution row produced, before it is shaped into a record."""

    output: str | None
    verdict: Verdict
    attempts: int
    metas: list[dict[str, Any]]


@dataclass(frozen=True)
class MultiOutcome:
    """What a multi-solution row produced.

    `solutions` are the attempts kept as output — every answered attempt, or
    only the passing ones under rejection sampling. `completed` holds each
    attempt the API answered, and `attempts` counts those it did not too.
    """

    solutions: list[Attempt]
    completed: list[Attempt]
    attempts: int


@dataclass(frozen=True)
class TaskResult:
    """One task's records in input order, with the counters its calls ran up."""

    name: str
    records: list[dict[str, Any]]
    stats: ClientStats


async def run_tasks(jobs: list[TaskJob]) -> list[TaskResult]:
    """Process every task concurrently and return their results in job order.

    Rows within a task, and the tasks themselves, are all in flight at once;
    each task's requests are paced by its own `rpm`, so the work of different
    tasks interleaves freely.
    """
    async with open_clients([job.config for job in jobs]) as clients:
        records = await asyncio.gather(
            *(_run_job(client, job) for client, job in zip(clients, jobs))
        )
    return [
        TaskResult(job.config.name, job_records, client.stats)
        for job, job_records, client in zip(jobs, records, clients)
    ]


async def _run_job(client: ChatClient, job: TaskJob) -> list[dict[str, Any]]:
    return await asyncio.gather(
        *(_run_row(client, job, prompt, row) for prompt, row in zip(job.prompts, job.rows))
    )


async def _run_row(
    client: ChatClient, job: TaskJob, prompt: RenderedPrompt, row: dict[str, Any]
) -> dict[str, Any]:
    """Generate one row's solutions and shape them into its output record."""
    config = job.config
    if not config.list_output:
        return _single_record(config, row, await _generate_one(client, config, prompt, row))
    collect = _collect_passing if config.generation.scheme == "rejection" else _collect_every
    return _multi_record(config, row, await collect(client, job, prompt, row))


async def _generate_one(
    client: ChatClient, config: TaskConfig, prompt: RenderedPrompt, row: dict[str, Any]
) -> RowOutcome:
    """A row of a single-solution task without ICL: one solution, or none."""
    if config.generation.scheme == "rejection":
        return await _run_rejection(client, config, prompt, row)

    attempt = await _attempt(client, config, prompt, row, None)
    if attempt is None:
        return _failed_outcome(config, attempts=1, metas=[])
    return RowOutcome(attempt.text, attempt.verdict, 1, [attempt.meta])


async def _run_rejection(
    client: ChatClient, config: TaskConfig, prompt: RenderedPrompt, row: dict[str, Any]
) -> RowOutcome:
    """Sample until a response passes the evaluation or the budget runs out."""
    metas: list[dict[str, Any]] = []
    for number in range(1, config.generation.n + 1):
        attempt = await _attempt(client, config, prompt, row, None)
        if attempt is None:
            continue
        metas.append(attempt.meta)
        if attempt.verdict.passed:
            return RowOutcome(attempt.text, attempt.verdict, number, metas)
    return _failed_outcome(config, attempts=config.generation.n, metas=metas)


async def _collect_every(
    client: ChatClient, job: TaskJob, prompt: RenderedPrompt, row: dict[str, Any]
) -> MultiOutcome:
    """Make one request per planned attempt; the evaluation gates none of them."""
    setups = _attempt_setups(job.config, job.icl)
    attempts = await asyncio.gather(
        *(_attempt(client, job.config, prompt, row, setup) for setup in setups)
    )
    answered = [attempt for attempt in attempts if attempt is not None]
    return MultiOutcome(solutions=answered, completed=answered, attempts=len(setups))


async def _collect_passing(
    client: ChatClient, job: TaskJob, prompt: RenderedPrompt, row: dict[str, Any]
) -> MultiOutcome:
    """Sample until enough responses pass the evaluation, or the budget is spent."""
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
    client: ChatClient,
    config: TaskConfig,
    prompt: RenderedPrompt,
    row: dict[str, Any],
    setup: PreparedSetup | None,
) -> Attempt | None:
    """Generate one response and judge it, or return None if the API never answered."""
    generation = config.generation
    if setup is not None:
        prompt = replace(prompt, examples=setup.turns)
    completion = await client.complete(prompt, generation.temperature, generation.max_tokens)
    if completion is None:
        return None
    verdict = await evaluate_response(config.evaluation, completion.text, row, client)
    meta = completion.meta
    if verdict.judge_meta is not None:
        meta = {**meta, "judge_meta": verdict.judge_meta}
    return Attempt(completion.text, meta, verdict, setup.name if setup else None)


def _failed_outcome(config: TaskConfig, attempts: int, metas: list[dict[str, Any]]) -> RowOutcome:
    """A row with no usable output; `passed` stays None when nothing judges it."""
    return RowOutcome(None, Verdict(passed=False if config.evaluation else None), attempts, metas)


def _single_record(config: TaskConfig, row: dict[str, Any], outcome: RowOutcome) -> dict[str, Any]:
    # One metadata object for single-attempt rows, a list once rejection sampling
    # made several attempts, and null when no attempt reached the API.
    metas = outcome.metas
    result = {
        "passed": outcome.verdict.passed,
        "extracted_answer": outcome.verdict.extracted_answer,
        "attempts": outcome.attempts,
    }
    if config.evaluation and config.evaluation.type == "llm_judge":
        result["judge_score"] = outcome.verdict.judge_score
    return {
        "input": row,
        "output": None if outcome.output is None else {config.output_field: outcome.output},
        "result": result,
        "meta": metas[0] if len(metas) == 1 else (metas or None),
    }


def _multi_record(config: TaskConfig, row: dict[str, Any], outcome: MultiOutcome) -> dict[str, Any]:
    """The list format: one output object per solution, one metadata per attempt."""
    passed = _passed_count(config, outcome)
    return {
        "input": row,
        "output": [
            {config.output_field: attempt.text, "icl_setup": attempt.setup_name}
            for attempt in outcome.solutions
        ],
        "result": {
            "passed": passed,
            "failed": outcome.attempts - passed,
            "attempts": outcome.attempts,
        },
        "meta": [
            {
                **attempt.meta,
                "icl_setup": attempt.setup_name,
                "evaluation_passed": attempt.verdict.passed,
            }
            for attempt in outcome.completed
        ],
    }


def _passed_count(config: TaskConfig, outcome: MultiOutcome) -> int:
    """Attempts the evaluation accepted, or the emitted solutions when none judges them."""
    if config.evaluation is None:
        return len(outcome.solutions)
    return sum(1 for attempt in outcome.completed if attempt.verdict.passed)


def summarize(results: list[TaskResult], multi: bool) -> dict[str, Any]:
    """Build the run summary printed to stdout.

    Rows with no evaluation configured count as passed as long as the API
    answered them. A multi-task run also reports the same counts per task,
    including the API calls its judge made.
    """
    stats = combine_stats([result.stats for result in results])
    elapsed = stats.elapsed_seconds
    summary = {
        **_counts([record for result in results for record in result.records]),
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(stats.api_calls / elapsed * 60, 1) if elapsed else 0.0,
    }
    if multi:
        summary["tasks"] = {
            result.name: {**_counts(result.records), "total_api_calls": result.stats.api_calls}
            for result in results
        }
    return summary


def _counts(records: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for record in records if _is_passed(record))
    solutions = sum(_solution_count(record) for record in records)
    total = len(records)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "total_solutions": solutions,
        "avg_solutions_per_input": round(solutions / total, 2) if total else 0.0,
    }


def _solution_count(record: dict[str, Any]) -> int:
    output = record["output"]
    return len(output) if isinstance(output, list) else int(output is not None)


def _is_passed(record: dict[str, Any]) -> bool:
    """A row passes once it has produced a solution nothing rejected."""
    if isinstance(record["output"], list):
        return record["result"]["passed"] > 0
    passed = record["result"]["passed"]
    return passed is True or (passed is None and record["output"] is not None)
