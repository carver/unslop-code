"""Per-row generation schemes: greedy, sample and rejection sampling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .api import CallMeta, ChatClient
from .config import TaskConfig
from .evaluation import EvalOutcome, evaluate
from .prompts import render_messages


@dataclass(frozen=True)
class RowOutcome:
    """Everything one input row produced, before it is shaped into JSON."""

    text: str | None
    passed: bool | None
    extracted: str | None
    attempts: int
    metas: list[CallMeta]
    judge_metas: list[CallMeta | None]
    judge_score: float | None
    api_calls: int


async def generate_row(
    client: ChatClient,
    judge_client: ChatClient | None,
    config: TaskConfig,
    row: Mapping[str, Any],
) -> RowOutcome:
    """Produce the outcome for one input row under the configured scheme.

    `greedy` and `sample` keep their single attempt whatever the evaluation
    says; `rejection` keeps the first passing attempt, and emits no output at
    all once its `n` attempts are spent.
    """
    messages = render_messages(config.prompt, row)
    rejecting = config.generation.scheme == "rejection"
    budget = config.generation.n if rejecting else 1

    metas: list[CallMeta] = []
    judge_metas: list[CallMeta | None] = []
    api_calls = 0
    attempt = 0
    for attempt in range(1, budget + 1):
        call = await client.complete(messages, config.generation.temperature)
        api_calls += call.requests
        if call.text is None:
            break
        evaluation = await evaluate(call.text, row, config.evaluation, judge_client)
        api_calls += evaluation.api_calls
        metas.append(call.meta)
        judge_metas.append(evaluation.judge_meta)
        if evaluation.passed or not rejecting:
            return _completed_row(call.text, evaluation, attempt, metas, judge_metas, api_calls)

    return _failed_row(config, attempt, metas, judge_metas, api_calls)


def _completed_row(
    text: str,
    evaluation: EvalOutcome,
    attempts: int,
    metas: list[CallMeta],
    judge_metas: list[CallMeta | None],
    api_calls: int,
) -> RowOutcome:
    return RowOutcome(
        text=text,
        passed=evaluation.passed,
        extracted=evaluation.extracted,
        attempts=attempts,
        metas=metas,
        judge_metas=judge_metas,
        judge_score=evaluation.judge_score,
        api_calls=api_calls,
    )


def _failed_row(
    config: TaskConfig,
    attempts: int,
    metas: list[CallMeta],
    judge_metas: list[CallMeta | None],
    api_calls: int,
) -> RowOutcome:
    """A row with no usable response: null output, and no verdict to report."""
    return RowOutcome(
        text=None,
        passed=False if config.evaluation else None,
        extracted=None,
        attempts=attempts,
        metas=metas,
        judge_metas=judge_metas,
        judge_score=None,
        api_calls=api_calls,
    )
