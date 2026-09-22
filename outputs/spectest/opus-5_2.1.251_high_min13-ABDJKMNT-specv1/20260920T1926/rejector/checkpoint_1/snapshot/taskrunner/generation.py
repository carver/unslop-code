"""Per-row generation schemes: greedy, sample and rejection sampling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .api import CallMeta, ChatClient
from .config import TaskConfig
from .evaluation import evaluate
from .prompts import build_messages


@dataclass(frozen=True)
class RowOutcome:
    """Everything one input row produced, before it is shaped into JSON."""

    text: str | None
    passed: bool | None
    extracted: str | None
    attempts: int
    metas: list[CallMeta]
    api_calls: int


async def generate_row(
    client: ChatClient, config: TaskConfig, row: Mapping[str, Any]
) -> RowOutcome:
    """Produce the outcome for one input row under the configured scheme."""
    messages = build_messages(config, row)
    scheme = _SCHEMES[config.generation.scheme]
    return await scheme(client, config, row, messages)


async def _single_attempt(
    client: ChatClient,
    config: TaskConfig,
    row: Mapping[str, Any],
    messages: list[dict[str, str]],
) -> RowOutcome:
    """Greedy and sample: one logical attempt, whatever the evaluation says."""
    call = await client.complete(messages, config.generation.temperature)
    if call.text is None:
        return _failed_row(config, attempts=1, metas=[], api_calls=call.requests)
    passed, extracted = evaluate(call.text, row, config.evaluation)
    return RowOutcome(
        text=call.text,
        passed=passed,
        extracted=extracted,
        attempts=1,
        metas=[call.meta],
        api_calls=call.requests,
    )


async def _rejection(
    client: ChatClient,
    config: TaskConfig,
    row: Mapping[str, Any],
    messages: list[dict[str, str]],
) -> RowOutcome:
    """Retry generation until an attempt passes evaluation or `n` is spent."""
    metas: list[CallMeta] = []
    api_calls = 0
    for attempt in range(1, config.generation.n + 1):
        call = await client.complete(messages, config.generation.temperature)
        api_calls += call.requests
        if call.text is None:
            return _failed_row(config, attempt, metas, api_calls)
        metas.append(call.meta)
        passed, extracted = evaluate(call.text, row, config.evaluation)
        if passed:
            return RowOutcome(call.text, True, extracted, attempt, metas, api_calls)
    return _failed_row(config, config.generation.n, metas, api_calls)


def _failed_row(
    config: TaskConfig, attempts: int, metas: list[CallMeta], api_calls: int
) -> RowOutcome:
    """A row with no usable response: null output, and no verdict to report."""
    passed = False if config.evaluation else None
    return RowOutcome(None, passed, None, attempts, metas, api_calls)


_SCHEMES = {
    "greedy": _single_attempt,
    "sample": _single_attempt,
    "rejection": _rejection,
}
