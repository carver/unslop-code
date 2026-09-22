"""Generation schemes: how many responses one row gets and which of them are kept.

Each scheme turns one row of a job into a `RowOutcome`. A task keeping the Part 1
result shape runs the `legacy_*` schemes, which produce at most one solution; the
others collect up to `num_solutions` and rotate through the ICL setups.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from client import Attempt, ChatClient
from config import TaskConfig
from evaluation import Verdict, evaluate
from icl import Setup, choose_setup, greedy_setups
from jobs import Job


@dataclass(frozen=True)
class AttemptOutcome:
    """One generation and its verdict. `text` is None when the API never answered."""

    text: str | None
    meta: dict | None
    verdict: Verdict
    setup: str | None


@dataclass(frozen=True)
class RowOutcome:
    """What one row produced: every attempt, the attempts kept as output, and the pass count."""

    attempts: list[AttemptOutcome]
    solutions: list[AttemptOutcome]
    passed: int


# A generation scheme turns one row of a job into its outcome.
Scheme = Callable[[ChatClient, Job, int], Awaitable[RowOutcome]]


def scheme_for(config: TaskConfig) -> Scheme:
    """The generation function each row of a task runs."""
    table = _LEGACY_SCHEMES if config.legacy else _SCHEMES
    return table[config.generation.scheme]


async def legacy_single(client: ChatClient, job: Job, index: int) -> RowOutcome:
    """Part 1 greedy and sample: one attempt, kept even when it fails evaluation."""
    return _outcome(job.config, [await _attempt(client, job, index, None)], passing_only=False)


async def legacy_rejection(client: ChatClient, job: Job, index: int) -> RowOutcome:
    """Part 1 rejection: up to `generation.n` attempts, keeping the first that passes."""
    attempts = []
    for _ in range(job.config.generation.n):
        attempts.append(await _attempt(client, job, index, None))
        if attempts[-1].verdict.passed:
            break
    return _outcome(job.config, attempts, passing_only=True)


async def greedy(client: ChatClient, job: Job, index: int) -> RowOutcome:
    """One deterministic attempt per selected setup, so the setups cap the solutions."""
    attempts = [
        await _attempt(client, job, index, setup)
        for setup in greedy_setups(job.config.icl, job.config.num_solutions)
    ]
    return _outcome(job.config, attempts, passing_only=False)


async def sample(client: ChatClient, job: Job, index: int) -> RowOutcome:
    """One sampled attempt per requested solution; evaluation does not gate the output."""
    attempts = [
        await _attempt(client, job, index, choose_setup(job.config.icl, number))
        for number in range(job.config.num_solutions)
    ]
    return _outcome(job.config, attempts, passing_only=False)


async def rejection(client: ChatClient, job: Job, index: int) -> RowOutcome:
    """Attempt until `num_solutions` responses have passed or `max_attempts` is spent."""
    config = job.config
    attempts: list[AttemptOutcome] = []
    passing = 0
    for number in range(config.generation.max_attempts):
        attempts.append(await _attempt(client, job, index, choose_setup(config.icl, number)))
        passing += bool(attempts[-1].verdict.passed)
        if passing == config.num_solutions:
            break
    return _outcome(config, attempts, passing_only=True)


_SCHEMES: dict[str, Scheme] = {"greedy": greedy, "sample": sample, "rejection": rejection}
_LEGACY_SCHEMES: dict[str, Scheme] = {
    "greedy": legacy_single,
    "sample": legacy_single,
    "rejection": legacy_rejection,
}


async def _attempt(client: ChatClient, job: Job, index: int, setup: Setup | None) -> AttemptOutcome:
    """Generate one response with the given setup and evaluate it."""
    name = None if setup is None else setup.name
    attempt = await client.complete(job.messages_for(index, setup))
    if attempt.text is None:
        return AttemptOutcome(None, None, Verdict(False, None), name)
    verdict = await evaluate(job.config.evaluation, attempt.text, job.rows[index], index, client)
    return AttemptOutcome(attempt.text, _meta(attempt, verdict), verdict, name)


def _meta(attempt: Attempt, verdict: Verdict) -> dict:
    """An attempt's metadata, carrying the judge call's own metadata when there was one."""
    if verdict.judge_meta is None:
        return attempt.meta
    return {**attempt.meta, "judge_meta": verdict.judge_meta}


def _outcome(config: TaskConfig, attempts: list[AttemptOutcome], passing_only: bool) -> RowOutcome:
    """Collect the attempts a row made. Rejection keeps only what passed; the rest keep every answer.

    Without an evaluation an attempt counts as passing as soon as the API answered it.
    """
    answered = [attempt for attempt in attempts if attempt.text is not None]
    if config.evaluation is None:
        return RowOutcome(attempts, answered, len(answered))
    passing = [attempt for attempt in answered if attempt.verdict.passed]
    return RowOutcome(attempts, passing if passing_only else answered, len(passing))
