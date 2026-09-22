"""Generation schemes: how many responses one row gets and which of them are kept.

Each scheme turns one row of a job into a `RowOutcome`. A task keeping the Part 1
result shape runs the `legacy_*` schemes, which produce at most one solution; the
others collect up to `num_solutions` and rotate through the ICL setups. The
`agentic` scheme replaces the single request of an attempt with a tool calling
loop, but is collected the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from agentic import run_loop
from client import ApiClient
from config import TaskConfig
from evaluation import Verdict, evaluate
from icl import Setup, choose_setup, greedy_setups
from jobs import Job
from schema import check_output


@dataclass(frozen=True)
class AttemptOutcome:
    """One generation and its verdict. `text` is None when the API never answered.

    `output` is what the attempt would be written out as: the response text, or
    the value parsed from it for a task with an `output_schema`, which sets
    `schema_error` instead when the response did not satisfy that schema.
    `iterations` and `tool_calls` describe the agentic loop behind the response
    and stay empty for the schemes that take a single request.
    """

    text: str | None
    meta: dict | None
    verdict: Verdict
    setup: str | None
    iterations: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    output: Any = None
    schema_error: str | None = None

    @property
    def usable(self) -> bool:
        """Whether the attempt produced an answer a task may write out."""
        return self.text is not None and self.schema_error is None


@dataclass(frozen=True)
class RowOutcome:
    """What one row produced: every attempt, the attempts kept as output, and the pass count."""

    attempts: list[AttemptOutcome]
    solutions: list[AttemptOutcome]
    passed: int


# A generation scheme turns one row of a job into its outcome.
Scheme = Callable[[ApiClient, Job, int], Awaitable[RowOutcome]]


def scheme_for(config: TaskConfig) -> Scheme:
    """The generation function each row of a task runs."""
    table = _LEGACY_SCHEMES if config.legacy else _SCHEMES
    return table[config.generation.scheme]


async def legacy_single(client: ApiClient, job: Job, index: int) -> RowOutcome:
    """Part 1 greedy and sample: one attempt, kept even when it fails evaluation."""
    return _outcome(job.config, [await _attempt(client, job, index, None)], passing_only=False)


async def legacy_rejection(client: ApiClient, job: Job, index: int) -> RowOutcome:
    """Part 1 rejection: up to `generation.n` attempts, keeping the first that passes."""
    attempts = []
    for _ in range(job.config.generation.n):
        attempts.append(await _attempt(client, job, index, None))
        if _passing(job.config, attempts[-1]):
            break
    return _outcome(job.config, attempts, passing_only=True)


async def greedy(client: ApiClient, job: Job, index: int) -> RowOutcome:
    """One deterministic attempt per selected setup, so the setups cap the solutions."""
    attempts = [
        await _attempt(client, job, index, setup)
        for setup in greedy_setups(job.config.icl, job.config.num_solutions)
    ]
    return _outcome(job.config, attempts, passing_only=False)


async def sample(client: ApiClient, job: Job, index: int) -> RowOutcome:
    """One sampled attempt per requested solution; evaluation does not gate the output."""
    attempts = [
        await _attempt(client, job, index, choose_setup(job.config.icl, number))
        for number in range(job.config.num_solutions)
    ]
    return _outcome(job.config, attempts, passing_only=False)


async def rejection(client: ApiClient, job: Job, index: int) -> RowOutcome:
    """Attempt until `num_solutions` responses have passed or `max_attempts` is spent."""
    config = job.config
    attempts: list[AttemptOutcome] = []
    passing = 0
    for number in range(config.generation.max_attempts):
        attempts.append(await _attempt(client, job, index, choose_setup(config.icl, number)))
        passing += _passing(config, attempts[-1])
        if passing == config.num_solutions:
            break
    return _outcome(config, attempts, passing_only=True)


async def legacy_agentic(client: ApiClient, job: Job, index: int) -> RowOutcome:
    """Part 1 shape: a single agentic loop, kept even when it fails evaluation."""
    return _outcome(job.config, [await _loop(client, job, index, None)], passing_only=False)


async def agentic(client: ApiClient, job: Job, index: int) -> RowOutcome:
    """One independent loop per requested solution, each with a setup from `strategy`."""
    attempts = [
        await _loop(client, job, index, choose_setup(job.config.icl, number))
        for number in range(job.config.num_solutions)
    ]
    return _outcome(job.config, attempts, passing_only=False)


_SCHEMES: dict[str, Scheme] = {
    "greedy": greedy,
    "sample": sample,
    "rejection": rejection,
    "agentic": agentic,
}
_LEGACY_SCHEMES: dict[str, Scheme] = {
    "greedy": legacy_single,
    "sample": legacy_single,
    "rejection": legacy_rejection,
    "agentic": legacy_agentic,
}


async def _loop(client: ApiClient, job: Job, index: int, setup: Setup | None) -> AttemptOutcome:
    """Run one agentic loop with the given setup and judge the text it ended on."""
    name = None if setup is None else setup.name
    loop = await run_loop(client, job, index, setup)
    if loop.text is None:
        return AttemptOutcome(
            None, loop.meta, Verdict(False, None), name, loop.iterations, loop.tool_calls
        )
    outcome = await _judged(client, job, index, loop.text, loop.meta, name)
    return replace(outcome, iterations=loop.iterations, tool_calls=loop.tool_calls)


async def _attempt(client: ApiClient, job: Job, index: int, setup: Setup | None) -> AttemptOutcome:
    """Generate one response with the given setup and judge it."""
    name = None if setup is None else setup.name
    attempt = await client.complete(job.messages_for(index, setup))
    if attempt.text is None:
        return AttemptOutcome(None, None, Verdict(False, None), name)
    return await _judged(client, job, index, attempt.text, attempt.meta, name)


async def _judged(
    client: ApiClient, job: Job, index: int, text: str, meta: dict, setup: str | None
) -> AttemptOutcome:
    """Validate one response against the task's schema, then evaluate it.

    A response that does not satisfy the schema is a failed attempt and is not
    evaluated any further.
    """
    structured = check_output(job.config.output_schema, text)
    if structured is not None and structured.error is not None:
        return AttemptOutcome(
            text, meta, Verdict(False, None), setup, schema_error=structured.error
        )
    verdict = await evaluate(job.config.evaluation, text, job.rows[index], index, client)
    return AttemptOutcome(
        text=text,
        meta=_meta(meta, verdict),
        verdict=verdict,
        setup=setup,
        output=text if structured is None else structured.value,
    )


def _meta(meta: dict, verdict: Verdict) -> dict:
    """An attempt's metadata, carrying the judge call's own metadata when there was one."""
    if verdict.judge_meta is None:
        return meta
    return {**meta, "judge_meta": verdict.judge_meta}


def _passing(config: TaskConfig, attempt: AttemptOutcome) -> bool:
    """Whether an attempt produced a solution.

    Without an evaluation an attempt passes as soon as the API answered it with
    something the task's schema accepts.
    """
    if not attempt.usable:
        return False
    return config.evaluation is None or bool(attempt.verdict.passed)


def _outcome(config: TaskConfig, attempts: list[AttemptOutcome], passing_only: bool) -> RowOutcome:
    """Collect the attempts a row made.

    Rejection keeps only what passed; the other schemes keep every answer.
    """
    answered = [attempt for attempt in attempts if attempt.usable]
    passing = [attempt for attempt in answered if _passing(config, attempt)]
    return RowOutcome(attempts, passing if passing_only else answered, len(passing))
