"""Collecting several solutions for one input row.

Used whenever a task configures ICL or asks for more than one solution; the
single-solution, no-ICL case keeps the Part 1 path in `runner`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import islice

from .api import ChatClient
from .config import TaskConfig
from .evaluation import NO_EVALUATION
from .icl import setup_sequence
from .prompts import build_messages


@dataclass(frozen=True)
class Solution:
    """One emitted response and the ICL setup that produced it."""

    text: str
    icl_setup: str | None


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
    client: ChatClient, task: TaskConfig, evaluator, row: dict
) -> MultiOutcome:
    """Generate until enough solutions are collected or the budget runs out.

    Rejection sampling keeps only responses that pass; the other schemes keep
    every response they receive, and evaluation merely labels it.
    """
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
        examples = task.icl.examples_of(setup) if setup else ()

        completion = await client.complete(build_messages(task.prompt, row, examples=examples))
        if completion is None:
            continue

        verdict = await evaluator.evaluate(completion.text, row) if evaluator else NO_EVALUATION
        completion.meta.update(icl_setup=name, evaluation_passed=verdict.passed)
        if verdict.judge_meta is not None:
            completion.meta["judge_meta"] = verdict.judge_meta
        metas.append(completion.meta)

        if verdict.passed:
            passed += 1
        if verdict.passed is not False or not gated:
            solutions.append(Solution(completion.text, name))

    collected = passed if evaluator else len(solutions)
    return MultiOutcome(row, solutions, attempts, collected, metas)


def _walks_setups(task: TaskConfig) -> bool:
    """Greedy decoding only varies by setup, so it visits each one once."""
    return task.generation.scheme == "greedy" and task.icl is not None and task.num_solutions > 1


def _attempt_budget(task: TaskConfig) -> int:
    """How many generation attempts one row of this task may make."""
    if task.generation.scheme == "rejection":
        return task.max_attempts
    if task.generation.scheme == "sample":
        return task.num_solutions
    return min(task.num_solutions, len(task.icl.setups)) if _walks_setups(task) else 1
