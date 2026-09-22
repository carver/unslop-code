"""Collecting several solutions for one input row.

Used whenever a task configures ICL or asks for more than one solution. Every
scheme walks the same loop: take the setup its strategy hands out, generate,
evaluate, and stop at the scheme's attempt budget -- or, for rejection, as soon
as enough attempts have passed. An `agentic` task generates by running a whole
tool-calling loop per solution instead of making a single request.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice

from .agentic import run_loop
from .api import Channel
from .config import TaskConfig
from .evaluation import Verdict
from .icl import IclSetup, setup_sequence
from .inputs import render_messages
from .scoring import attempt_meta, failure_verdict, score_response

GATED_SCHEME = "rejection"
PARALLEL_SCHEMES = ("sample", "agentic")


@dataclass(frozen=True)
class Solution:
    """One emitted solution and the ICL setup that produced it."""

    output: object
    setup_name: str | None


@dataclass(frozen=True)
class MultiOutcome:
    """What one input row produced in the list output format."""

    solutions: list[Solution]
    passed: int
    failed: int
    attempts: int
    metas: list[dict]

    @property
    def solution_count(self) -> int:
        return len(self.solutions)

    @property
    def row_passed(self) -> bool:
        """A row counts as passed once one of its solutions passed."""
        return self.passed > 0


@dataclass(frozen=True)
class _Attempt:
    """One generation, whether or not it produced a usable response."""

    setup: IclSetup | None
    content: str | None
    verdict: Verdict
    meta: dict | None


async def collect_solutions(
    row: dict, task: TaskConfig, channel: Channel
) -> MultiOutcome:
    """Generate for `row` until the task's budget or its solution target is met."""
    gated = task.generation.scheme == GATED_SCHEME
    ordered = _walks_setups(task)
    attempts: list[_Attempt] = []
    passing = 0
    setups = setup_sequence(task.icl, ordered)
    for setup in islice(setups, _attempt_budget(task, ordered)):
        attempt = await _attempt(row, task, channel, setup)
        attempts.append(attempt)
        passing += bool(attempt.verdict.passed)
        if gated and passing >= task.num_solutions:
            break
    return _outcome(attempts, task, gated)


async def _attempt(
    row: dict, task: TaskConfig, channel: Channel, setup: IclSetup | None
) -> _Attempt:
    """Produce one solution with `setup`'s examples and evaluate it."""
    if task.is_agentic:
        return await _agentic_attempt(row, task, channel, setup)

    messages = render_messages(row, task, setup)
    completion = await channel.client.complete(
        messages, task.generation.temperature, channel.generation
    )
    if completion is None:
        return _Attempt(setup, None, failure_verdict(task), None)

    verdict = await score_response(completion.content, task, row, channel)
    meta = attempt_meta(completion, verdict, task)
    return _Attempt(setup, completion.content, verdict, _tagged(meta, setup, verdict))


async def _agentic_attempt(
    row: dict, task: TaskConfig, channel: Channel, setup: IclSetup | None
) -> _Attempt:
    """One agentic loop, whose aggregated metadata joins its meta entry."""
    run = await run_loop(row, task, channel, setup)
    verdict = (
        failure_verdict(task)
        if run.content is None
        else await score_response(run.content, task, row, channel)
    )
    meta = _tagged(run.meta, setup, verdict) if run.iterations else None
    return _Attempt(setup, run.content, verdict, meta)


def _tagged(meta: dict, setup: IclSetup | None, verdict: Verdict) -> dict:
    """One attempt's metadata, with the ICL and evaluation fields appended."""
    return {
        **meta,
        "icl_setup": None if setup is None else setup.name,
        "evaluation_passed": verdict.passed,
    }


def _walks_setups(task: TaskConfig) -> bool:
    """Greedy visits each setup once instead of following the strategy."""
    return (
        task.generation.scheme == "greedy"
        and task.icl is not None
        and task.num_solutions > 1
    )


def _attempt_budget(task: TaskConfig, ordered: bool) -> int:
    """How many generations one row may make under the task's scheme.

    Greedy is deterministic, so it only repeats across setups; its sequence of
    setups runs out on its own once each has been used.
    """
    if task.generation.scheme == GATED_SCHEME:
        return task.max_attempts
    if task.generation.scheme in PARALLEL_SCHEMES:
        return task.num_solutions
    return task.num_solutions if ordered else 1


def _outcome(attempts: list[_Attempt], task: TaskConfig, gated: bool) -> MultiOutcome:
    """Turn the attempts into the solutions and counts the row reports."""
    emitted = [
        attempt
        for attempt in attempts
        if attempt.content is not None and (not gated or attempt.verdict.passed)
    ]
    solutions = [
        Solution(
            attempt.verdict.output,
            None if attempt.setup is None else attempt.setup.name,
        )
        for attempt in emitted
    ]
    passed = (
        len(solutions)
        if task.evaluation is None
        else sum(1 for attempt in attempts if attempt.verdict.passed)
    )
    return MultiOutcome(
        solutions=solutions,
        passed=passed,
        failed=len(attempts) - passed,
        attempts=len(attempts),
        metas=[attempt.meta for attempt in attempts if attempt.meta is not None],
    )
