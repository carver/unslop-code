"""Per-row generation: how many attempts a row gets and which ones it keeps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .api import CallMeta, ChatClient
from .config import TaskConfig
from .evaluation import EvalOutcome, evaluate
from .icl import DECLARED_ORDER, examples_for, select_setup
from .prompts import render_messages


@dataclass(frozen=True)
class AttemptOutcome:
    """One generation attempt: its response, the setup it used, its verdict."""

    text: str | None
    icl_setup: str | None
    evaluation: EvalOutcome
    meta: CallMeta | None

    @property
    def passed(self) -> bool | None:
        return self.evaluation.passed


@dataclass(frozen=True)
class RowOutcome:
    """Everything one input row produced, before it is shaped into JSON.

    `solutions` are the attempts the scheme kept; `legacy` marks a row that
    still reports itself in the Part 1 single-solution format.
    """

    attempts: list[AttemptOutcome]
    solutions: list[AttemptOutcome]
    api_calls: int
    legacy: bool

    @property
    def passed_count(self) -> int:
        """Kept solutions the evaluation accepted, or all of them without one."""
        return sum(1 for solution in self.solutions if solution.passed is not False)


@dataclass(frozen=True)
class AttemptPlan:
    """How many attempts a row may spend and how each one picks its setup."""

    budget: int
    strategy: str | None
    gated: bool
    legacy: bool


def plan_attempts(config: TaskConfig) -> AttemptPlan:
    """Derive a row's attempt budget and setup order from its scheme.

    Only `rejection` gates on evaluation; the other schemes keep every
    response they get. A task that asks for one solution without ICL keeps the
    Part 1 behaviour, including its `generation.n` rejection budget.
    """
    legacy = config.num_solutions == 1 and config.icl is None
    strategy = _strategy(config)
    return AttemptPlan(
        budget=_budget(config, strategy, legacy),
        strategy=strategy,
        gated=config.generation.scheme == "rejection",
        legacy=legacy,
    )


def _strategy(config: TaskConfig) -> str | None:
    """`None` without ICL; greedy multi-solution runs walk setups in order."""
    if config.icl is None:
        return None
    if config.generation.scheme == "greedy" and config.num_solutions > 1:
        return DECLARED_ORDER
    return config.icl.strategy


def _budget(config: TaskConfig, strategy: str | None, legacy: bool) -> int:
    """`rejection` retries up to its attempt budget, `sample` asks once per
    requested solution, and `greedy` gets one attempt per available setup."""
    scheme = config.generation.scheme
    if scheme == "rejection":
        return config.generation.n if legacy else config.generation.max_attempts
    if scheme == "sample":
        return config.num_solutions
    return len(config.icl.setups) if strategy == DECLARED_ORDER else 1


async def generate_row(
    client: ChatClient,
    judge_client: ChatClient | None,
    config: TaskConfig,
    row: Mapping[str, Any],
) -> RowOutcome:
    """Run one row's attempts and collect the solutions its scheme admits.

    The loop ends once `num_solutions` solutions are collected or the budget
    runs out. A legacy row also ends at its first unusable response, while a
    multi-solution row counts that attempt and moves on to the next one.
    """
    plan = plan_attempts(config)
    attempts: list[AttemptOutcome] = []
    solutions: list[AttemptOutcome] = []
    api_calls = 0

    for index in range(plan.budget):
        setup = select_setup(config.icl, plan.strategy, index)
        name = setup.name if setup else None
        messages = render_messages(config.prompt, row, examples_for(config.icl, setup))
        call = await client.complete(messages, config.generation.temperature)
        api_calls += call.requests

        if call.text is None:
            attempts.append(_unanswered(name))
            if plan.legacy:
                break
            continue

        verdict = await evaluate(call.text, row, config.evaluation, judge_client)
        api_calls += verdict.api_calls
        attempt = AttemptOutcome(call.text, name, verdict, call.meta)
        attempts.append(attempt)
        if verdict.passed or not plan.gated:
            solutions.append(attempt)
        if len(solutions) >= config.num_solutions:
            break

    return RowOutcome(attempts, solutions, api_calls, plan.legacy)


def _unanswered(setup: str | None) -> AttemptOutcome:
    """An attempt whose request never came back with a usable response."""
    return AttemptOutcome(
        text=None,
        icl_setup=setup,
        evaluation=EvalOutcome(passed=None, extracted=None),
        meta=None,
    )
