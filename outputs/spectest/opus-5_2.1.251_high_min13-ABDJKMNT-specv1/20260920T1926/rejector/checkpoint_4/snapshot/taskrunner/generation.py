"""Per-row generation: how many attempts a row gets and which ones it keeps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .agentic import AgenticOutcome, run_loop
from .api import CallMeta, ModelClient
from .config import TaskConfig
from .evaluation import EvalOutcome, evaluate
from .icl import DECLARED_ORDER, examples_for, select_setup
from .prompts import render_messages

# The scheme whose attempts are whole tool-calling loops rather than one call.
AGENTIC = "agentic"


@dataclass(frozen=True)
class AttemptOutcome:
    """One generation attempt: its response, the setup it used, its verdict.

    An agentic attempt is a whole loop, so it reports its model calls through
    `agentic` instead of a single `meta`.
    """

    text: str | None
    icl_setup: str | None
    evaluation: EvalOutcome
    meta: CallMeta | None
    agentic: AgenticOutcome | None = None

    @property
    def passed(self) -> bool | None:
        return self.evaluation.passed

    @property
    def metas(self) -> list[CallMeta]:
        """Every model call the attempt made, one per agentic iteration."""
        if self.agentic is not None:
            return self.agentic.metas
        return [self.meta] if self.meta else []


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
    """`rejection` retries up to its attempt budget, `sample` and `agentic`
    ask once per requested solution, and `greedy` gets one attempt per
    available setup."""
    scheme = config.generation.scheme
    if scheme == "rejection":
        return config.generation.n if legacy else config.generation.max_attempts
    if scheme in ("sample", AGENTIC):
        return config.num_solutions
    return len(config.icl.setups) if strategy == DECLARED_ORDER else 1


@dataclass(frozen=True)
class _Response:
    """What one attempt got back, whichever scheme produced it."""

    text: str | None
    meta: CallMeta | None
    agentic: AgenticOutcome | None
    requests: int


async def _respond(
    client: ModelClient, config: TaskConfig, messages: list[dict[str, Any]]
) -> _Response:
    """Spend one attempt: a whole agentic loop, or a single completion."""
    if config.generation.scheme == AGENTIC:
        loop = await run_loop(client, config, messages)
        return _Response(loop.text, None, loop, loop.requests)
    call = await client.complete(messages, config.generation.temperature)
    return _Response(call.text, call.meta, None, call.requests)


async def generate_row(
    client: ModelClient,
    judge_client: ModelClient | None,
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
        response = await _respond(client, config, messages)
        api_calls += response.requests

        if response.text is None:
            attempts.append(_unanswered(name, response.agentic))
            if plan.legacy:
                break
            continue

        verdict = await evaluate(response.text, row, config.evaluation, judge_client)
        api_calls += verdict.api_calls
        attempt = AttemptOutcome(response.text, name, verdict, response.meta, response.agentic)
        attempts.append(attempt)
        if verdict.passed or not plan.gated:
            solutions.append(attempt)
        if len(solutions) >= config.num_solutions:
            break

    return RowOutcome(attempts, solutions, api_calls, plan.legacy)


def _unanswered(setup: str | None, loop: AgenticOutcome | None) -> AttemptOutcome:
    """An attempt that produced no text: a failed request or a spent loop."""
    return AttemptOutcome(
        text=None,
        icl_setup=setup,
        evaluation=EvalOutcome(passed=None, extracted=None),
        meta=None,
        agentic=loop,
    )
