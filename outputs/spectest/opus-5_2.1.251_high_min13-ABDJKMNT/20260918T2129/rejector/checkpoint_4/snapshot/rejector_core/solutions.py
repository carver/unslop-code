"""Collecting several solutions for one input row.

Used whenever a task configures ICL or asks for more than one solution; the
single-solution, no-ICL case keeps the Part 1 path in `runner`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import islice

from .agentic import run_loop
from .api import ModelClient
from .config import TaskConfig
from .evaluation import judge
from .icl import IclExample, setup_sequence
from .prompts import build_messages


@dataclass(frozen=True)
class Solution:
    """One emitted response and the ICL setup that produced it."""

    text: str
    icl_setup: str | None


@dataclass(frozen=True)
class Attempt:
    """One generation attempt: the text it kept, if any, and its metadata.

    `meta` is None only when the request itself never came back, which leaves
    nothing to report for that attempt.
    """

    text: str | None
    meta: dict | None


@dataclass
class MultiOutcome:
    """What one input row produced in the multi-solution output format."""

    row: dict
    solutions: list[Solution]
    attempts: int
    passed: int
    metas: list[dict] = field(default_factory=list)

    @property
    def failed(self) -> int:
        """Attempts that did not contribute a passing solution."""
        return self.attempts - self.passed


async def collect_solutions(
    client: ModelClient, task: TaskConfig, evaluator, row: dict
) -> MultiOutcome:
    """Generate until enough solutions are collected or the budget runs out.

    Rejection sampling keeps only responses that pass; the other schemes keep
    every response they receive, and evaluation merely labels it.
    """
    generate = _agentic_attempt if task.generation.scheme == "agentic" else _single_attempt
    gated = task.generation.scheme == "rejection"
    solutions: list[Solution] = []
    metas: list[dict] = []
    passed = 0
    attempts = 0

    for setup in islice(setup_sequence(task.icl, _walks_setups(task)), _attempt_budget(task)):
        if len(solutions) >= task.num_solutions:
            break
        attempts += 1
        name = setup.name if setup else None

        attempt = await generate(client, task, row, task.icl.examples_of(setup) if setup else ())
        if attempt.meta is None:
            continue

        verdict = await judge(evaluator, attempt.text, row)
        attempt.meta.update(icl_setup=name, evaluation_passed=verdict.passed)
        if verdict.judge_meta is not None:
            attempt.meta["judge_meta"] = verdict.judge_meta
        metas.append(attempt.meta)

        if verdict.passed:
            passed += 1
        if attempt.text is not None and (verdict.passed is not False or not gated):
            solutions.append(Solution(attempt.text, name))

    collected = passed if evaluator else len(solutions)
    return MultiOutcome(row, solutions, attempts, collected, metas)


async def _single_attempt(
    client: ModelClient, task: TaskConfig, row: dict, examples: Sequence[IclExample]
) -> Attempt:
    """One API request answering the row directly."""
    completion = await client.complete(build_messages(task.prompt, row, examples=examples))
    return Attempt(None, None) if completion is None else Attempt(completion.text, completion.meta)


async def _agentic_attempt(
    client: ModelClient, task: TaskConfig, row: dict, examples: Sequence[IclExample]
) -> Attempt:
    """One whole agentic loop, whose aggregated metadata is the attempt's."""
    loop = await run_loop(client, task, row, examples)
    return Attempt(loop.output, loop.meta)


def _walks_setups(task: TaskConfig) -> bool:
    """Greedy decoding only varies by setup, so it visits each one once."""
    return task.generation.scheme == "greedy" and task.icl is not None and task.num_solutions > 1


def _attempt_budget(task: TaskConfig) -> int:
    """How many generation attempts one row of this task may make."""
    if task.generation.scheme == "rejection":
        return task.max_attempts
    if task.generation.scheme in ("sample", "agentic"):
        return task.num_solutions
    return min(task.num_solutions, len(task.icl.setups)) if _walks_setups(task) else 1
