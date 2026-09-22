"""Per-row generation: greedy, sample, and rejection sampling over ICL setups."""

from __future__ import annotations

from dataclasses import dataclass, field

from rejlib.api import ChatClient
from rejlib.config import TaskConfig
from rejlib.evaluation import Evaluator, Verdict
from rejlib.icl import Setup
from rejlib.prompts import build_messages


@dataclass
class Try:
    """One logical generation attempt: its text, the setup used, and the verdict."""

    content: str | None
    meta: dict
    setup: str | None
    #: ``None`` when the task configures no evaluation.
    verdict: Verdict | None = None

    @property
    def passed(self) -> bool | None:
        """Whether evaluation accepted this attempt; ``None`` when nothing judged it."""
        return None if self.verdict is None else self.verdict.passed


@dataclass
class Outcome:
    """Every attempt one input row made, and the attempts kept as solutions."""

    tries: list[Try] = field(default_factory=list)
    kept: list[Try] = field(default_factory=list)

    @property
    def attempts(self) -> int:
        """Logical generation attempts; HTTP retries do not count (T2)."""
        return len(self.tries)

    @property
    def metas(self) -> list[dict]:
        return [attempt.meta for attempt in self.tries]

    def add(self, attempt: Try, keep: bool) -> None:
        self.tries.append(attempt)
        if keep:
            self.kept.append(attempt)


async def generate(client: ChatClient, config: TaskConfig, evaluator: Evaluator | None,
                   row: dict) -> Outcome:
    """Run the configured scheme for one row."""
    if config.generation.scheme == "rejection":
        return await _rejection(client, config, evaluator, row)
    if config.generation.scheme == "greedy":
        return await _greedy(client, config, evaluator, row)
    return await _sample(client, config, evaluator, row)


async def _greedy(client: ChatClient, config: TaskConfig, evaluator: Evaluator | None,
                  row: dict) -> Outcome:
    """One deterministic generation per setup, each setup used at most once.

    Every produced response is kept, so evaluation does not gate the output.
    """
    outcome = Outcome()
    for setup in _greedy_setups(config):
        attempt = await _attempt(client, config, evaluator, row, setup)
        outcome.add(attempt, keep=attempt.content is not None)
        if len(outcome.kept) == config.num_solutions:
            break
    return outcome


async def _sample(client: ChatClient, config: TaskConfig, evaluator: Evaluator | None,
                  row: dict) -> Outcome:
    """One sampled generation per requested solution; evaluation does not gate it."""
    outcome = Outcome()
    for index in range(config.num_solutions):
        attempt = await _attempt(client, config, evaluator, row, _setup(config, index))
        outcome.add(attempt, keep=attempt.content is not None)
    return outcome


async def _rejection(client: ChatClient, config: TaskConfig, evaluator: Evaluator,
                     row: dict) -> Outcome:
    """Generate until ``num_solutions`` attempts pass or the attempt budget runs out.

    An attempt whose HTTP requests were exhausted counts as a failed attempt and
    the remaining attempts still run (T8).
    """
    outcome = Outcome()
    for index in range(config.rejection_attempts):
        attempt = await _attempt(client, config, evaluator, row, _setup(config, index))
        outcome.add(attempt, keep=attempt.passed is True)
        if len(outcome.kept) == config.num_solutions:
            break
    return outcome


def _greedy_setups(config: TaskConfig) -> list[Setup | None]:
    """The setups greedy walks: declared order for several solutions (T45)."""
    if config.icl is None:
        return [None]  # T41: one prompt means at most one deterministic solution
    if config.num_solutions == 1:
        return [config.icl.select(0)]
    return list(config.icl.setups)


def _setup(config: TaskConfig, attempt: int) -> Setup | None:
    """The setup the numbered attempt uses under the configured strategy."""
    return None if config.icl is None else config.icl.select(attempt)


async def _attempt(client: ChatClient, config: TaskConfig, evaluator: Evaluator | None,
                   row: dict, setup: Setup | None) -> Try:
    """Generate once with ``setup``'s demonstrations and evaluate the response."""
    examples = config.icl.examples(setup) if setup is not None else ()
    attempt = await client.complete(build_messages(config, row, examples))
    name = setup.name if setup is not None else None

    if evaluator is None:
        return Try(attempt.content, attempt.meta, name)  # verdict stays None (T21)
    if attempt.content is None:
        return Try(None, attempt.meta, name, Verdict(passed=False))

    verdict = await evaluator.verdict(attempt.content, row)
    if verdict.judge_meta is not None:
        attempt.meta["judge_meta"] = verdict.judge_meta  # T26
    return Try(attempt.content, attempt.meta, name, verdict)
