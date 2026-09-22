"""Evaluating a response against its input row."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rejlib.api import ChatClient
from rejlib.config import Evaluation, TaskConfig
from rejlib.extraction import extract_answer
from rejlib.judge import Judge
from rejlib.script_eval import run_command

#: Judging is a scoring call, not a sampled generation (T25).
JUDGE_TEMPERATURE = 0.0


@dataclass
class Verdict:
    """What one evaluation decided about one response."""

    passed: bool
    extracted: str | None = None
    judge_score: int | float | None = None
    judge_meta: dict | None = None


class Evaluator:
    """Applies one task's evaluation to a response.

    `script` and `llm_judge` reach outside the process, so judging is async; the
    Part 1 types are decided in memory.
    """

    def __init__(self, evaluation: Evaluation, judge: Judge | None = None):
        self._evaluation = evaluation
        self._judge = judge

    async def verdict(self, text: str, row: dict) -> Verdict:
        evaluation = self._evaluation
        if evaluation.type == "llm_judge":
            return await self._judged(text, row)
        extracted = extract_answer(text, evaluation.extract)
        if evaluation.type == "script":
            return Verdict(await run_command(evaluation.script, row, text), extracted)
        return Verdict(*evaluate(evaluation, text, row))

    async def _judged(self, text: str, row: dict) -> Verdict:
        """Score the response with the judge model and compare against the threshold."""
        result = await self._judge.score(text, row)
        threshold = self._evaluation.judge.threshold
        return Verdict(
            passed=result.score is not None and result.score >= threshold,
            extracted=result.extracted,
            judge_score=result.score,
            judge_meta=result.meta,
        )


def build_evaluator(config: TaskConfig, client: ChatClient) -> Evaluator | None:
    """The task's evaluator, wired to a judge client when the task judges.

    The judge shares the task's connection, rate budget and counters, so its
    calls are paced and counted like any other request.
    """
    if config.evaluation is None:
        return None
    judge = None
    if config.evaluation.judge:
        spec = config.evaluation.judge
        judge = Judge(
            client.variant(model=spec.model or config.model, temperature=JUDGE_TEMPERATURE),
            spec,
            config.evaluation.extract,
        )
    return Evaluator(config.evaluation, judge)


def evaluate(evaluation: Evaluation, text: str, row: dict) -> tuple[bool, str | None]:
    """Judge one response in memory, returning ``(passed, extracted_answer)``."""
    extracted = extract_answer(text, evaluation.extract)
    if evaluation.type == "regex":
        return bool(re.search(evaluation.pattern, text)), extracted

    expected = str(row[evaluation.answer_field])
    if evaluation.type == "contains":
        return expected in text, extracted
    return _exact_match(extracted, expected), extracted


def _exact_match(extracted: str | None, expected: str) -> bool:
    """Numbers compare by value, anything else by stripped text (T6)."""
    if extracted is None:
        return False
    numbers = _as_numbers(extracted, expected)
    if numbers is not None:
        return numbers[0] == numbers[1]
    return extracted.strip() == expected.strip()


def _as_numbers(*values: str) -> list[float] | None:
    try:
        return [float(value.replace(",", "").strip()) for value in values]
    except ValueError:
        return None
