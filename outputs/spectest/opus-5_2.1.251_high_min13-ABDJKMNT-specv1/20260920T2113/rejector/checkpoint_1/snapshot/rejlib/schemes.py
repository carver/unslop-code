"""Per-row generation schemes: greedy, sample, and rejection sampling."""

from __future__ import annotations

from dataclasses import dataclass, field

from rejlib.api import ChatClient
from rejlib.config import TaskConfig
from rejlib.evaluation import evaluate
from rejlib.prompts import build_messages


@dataclass
class Outcome:
    """What one input row produced: the kept text, its verdict, and metadata."""

    content: str | None = None
    passed: bool | None = None
    extracted: str | None = None
    metas: list[dict] = field(default_factory=list)

    @property
    def attempts(self) -> int:
        """Logical generation attempts; HTTP retries do not count (T2)."""
        return len(self.metas)


async def generate(client: ChatClient, config: TaskConfig, row: dict) -> Outcome:
    """Run the configured scheme for one row."""
    messages = build_messages(config, row)
    if config.generation.scheme == "rejection":
        return await _rejection(client, config, row, messages)
    return await _single(client, config, row, messages)


async def _single(client: ChatClient, config: TaskConfig, row: dict,
                  messages: list[dict]) -> Outcome:
    """greedy and sample: one logical attempt, kept whatever the evaluation says."""
    attempt = await client.complete(messages)
    outcome = Outcome(content=attempt.content, metas=[attempt.meta])
    if config.evaluation is None:
        return outcome  # passed stays None, even for a failed call (T21)
    if attempt.content is None:
        outcome.passed = False
    else:
        outcome.passed, outcome.extracted = evaluate(config.evaluation, attempt.content, row)
    return outcome


async def _rejection(client: ChatClient, config: TaskConfig, row: dict,
                     messages: list[dict]) -> Outcome:
    """Sample up to ``n`` times, keeping the first response that passes evaluation.

    An attempt whose HTTP requests were exhausted counts as a failed attempt and
    the remaining attempts still run (T8).
    """
    exhausted = Outcome(passed=False)
    for _ in range(config.generation.n):
        attempt = await client.complete(messages)
        exhausted.metas.append(attempt.meta)
        if attempt.content is None:
            continue
        passed, extracted = evaluate(config.evaluation, attempt.content, row)
        if passed:
            return Outcome(
                content=attempt.content, passed=True, extracted=extracted,
                metas=exhausted.metas,
            )
    return exhausted
