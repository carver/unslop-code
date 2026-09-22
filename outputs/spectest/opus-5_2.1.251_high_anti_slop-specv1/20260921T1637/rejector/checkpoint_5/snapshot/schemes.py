"""Per-row generation schemes: greedy, sample, and rejection sampling."""

from typing import Any

from agentic import generate_agentic_row
from api import ModelClient
from config import TaskConfig
from dataset import Messages
from evaluation import Verdict, failed_verdict, grade
from icl import DEFAULT_STRATEGY, RenderedSetup, build_messages, setup_for_attempt
from results import Attempt, MultiOutcome, Outcome, RowOutcome, Solution


async def generate_row(
    client: ModelClient,
    judge: ModelClient | None,
    task: TaskConfig,
    messages: Messages,
    setups: tuple[RenderedSetup, ...],
    row: dict[str, Any],
) -> Outcome:
    """Produce one row's outcome in the format its task calls for.

    A task asking for a single solution without ICL keeps the Part 1 behaviour
    and output shape; anything else collects up to ``num_solutions`` solutions.
    """
    if task.generation.scheme == "agentic":
        return await generate_agentic_row(client, judge, task, messages, setups, row)
    if task.num_solutions == 1 and task.icl is None:
        return await _generate_one(client, judge, task, messages, row)
    return await _generate_many(client, judge, task, messages, setups, row)


async def _generate_one(
    client: ModelClient,
    judge: ModelClient | None,
    task: TaskConfig,
    messages: Messages,
    row: dict[str, Any],
) -> RowOutcome:
    """``greedy`` and ``sample`` keep their single response; ``rejection`` retries up to ``n`` times."""
    generation = task.generation
    rejecting = generation.scheme == "rejection"
    attempts: list[Attempt] = []
    for _ in range(generation.n if rejecting else 1):
        completion = await client.complete(messages, generation.temperature, generation.max_tokens)
        if completion.text is None:
            attempts.append(Attempt(completion.meta))
            break
        verdict = await grade(task, completion.text, row, judge)
        attempts.append(Attempt(completion.meta, verdict.judge_meta))
        if verdict.passed or not rejecting:
            return _row_outcome(row, verdict, attempts)
    return _row_outcome(row, failed_verdict(task), attempts)


def _row_outcome(row: dict[str, Any], verdict: Verdict, attempts: list[Attempt]) -> RowOutcome:
    """One row's result, taking everything the response was graded on from ``verdict``."""
    return RowOutcome(
        row=row,
        output=verdict.output,
        passed=verdict.passed,
        extracted_answer=verdict.extracted_answer,
        judge_score=verdict.judge_score,
        attempts=attempts,
        schema_valid=verdict.schema_valid,
        schema_error=verdict.schema_error,
    )


async def _generate_many(
    client: ModelClient,
    judge: ModelClient | None,
    task: TaskConfig,
    messages: Messages,
    setups: tuple[RenderedSetup, ...],
    row: dict[str, Any],
) -> MultiOutcome:
    """Work through the planned attempts until ``num_solutions`` solutions are collected.

    Only ``rejection`` lets the evaluation decide whether a response is kept;
    the other schemes keep every response they get. A response that fails the
    task's ``output_schema`` has no value to keep under any scheme.
    """
    generation = task.generation
    gating = generation.scheme == "rejection"
    solutions: list[Solution] = []
    attempts: list[Attempt] = []
    for setup in _planned_setups(task, setups):
        prompt = build_messages(messages, setup)
        completion = await client.complete(prompt, generation.temperature, generation.max_tokens)
        if completion.text is None:
            attempts.append(Attempt(completion.meta, icl_setup=setup.name))
            continue
        verdict = await grade(task, completion.text, row, judge)
        attempts.append(Attempt(completion.meta, verdict.judge_meta, setup.name, verdict.passed))
        if verdict.output is not None and (verdict.passed or not gating):
            solutions.append(Solution(verdict.output, setup.name))
        if len(solutions) == task.num_solutions:
            break
    return MultiOutcome(row, solutions, attempts, graded=task.graded)


def _planned_setups(task: TaskConfig, setups: tuple[RenderedSetup, ...]) -> list[RenderedSetup]:
    """The ICL setup of every attempt the row may make, at most ``max_attempts`` of them.

    Greedy generation repeated against one setup would only repeat its answer,
    so several greedy solutions come from walking the setups in declared order,
    each used at most once, rather than from the configured strategy.
    """
    generation = task.generation
    if generation.scheme == "greedy" and task.num_solutions > 1:
        return list(setups[: task.num_solutions])
    count = generation.max_attempts if generation.scheme == "rejection" else task.num_solutions
    strategy = task.icl.strategy if task.icl else DEFAULT_STRATEGY
    return [setup_for_attempt(setups, strategy, attempt) for attempt in range(count)]
