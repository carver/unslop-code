"""Response evaluation: local matching, shell scripts, and LLM judges."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from .api import ModelClient
from .config import Evaluation, TaskConfig
from .extraction import as_number, extract_answer
from .prompts import build_messages
from .templates import render

SCRIPT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Verdict:
    """The outcome of evaluating one response."""

    passed: bool | None
    extracted: str | None = None
    judge_score: float | None = None
    judge_meta: dict | None = None


NO_EVALUATION = Verdict(passed=None)


class MatchEvaluator:
    """`exact_match`, `contains` and `regex`: judged locally against the row."""

    def __init__(self, evaluation: Evaluation):
        self._evaluation = evaluation
        self._pattern = re.compile(evaluation.pattern) if evaluation.type == "regex" else None

    async def evaluate(self, text: str, row: dict) -> Verdict:
        extracted = extract_answer(text, self._evaluation.extract)
        if self._evaluation.type == "regex":
            return Verdict(self._pattern.search(text) is not None, extracted)

        expected = str(row[self._evaluation.answer_field])
        if self._evaluation.type == "contains":
            return Verdict(expected in text, extracted)
        return Verdict(_matches(extracted, expected), extracted)


class ScriptEvaluator:
    """`script`: renders a shell command and compares its exit code."""

    def __init__(self, evaluation: Evaluation):
        self._evaluation = evaluation

    async def evaluate(self, text: str, row: dict) -> Verdict:
        command = render(self._evaluation.command_template, row, response=text)
        exit_code = await _run_command(command)
        return Verdict(exit_code == self._evaluation.success_exit_code)


class JudgeEvaluator:
    """`llm_judge`: scores the response with a second model call."""

    def __init__(self, evaluation: Evaluation, client: ModelClient, model: str):
        self._evaluation = evaluation
        self._client = client
        self._model = model

    async def evaluate(self, text: str, row: dict) -> Verdict:
        messages = build_messages(self._evaluation.judge_prompt, row, response=text)
        completion = await self._client.complete(messages, model=self._model)
        if completion is None:
            return Verdict(passed=False)

        extracted = extract_answer(completion.text, self._evaluation.extract)
        score = _as_score(extracted)
        passed = score is not None and score >= self._evaluation.threshold
        return Verdict(passed, extracted, score, completion.meta)


async def judge(evaluator, text: str | None, row: dict) -> Verdict:
    """Evaluate one response; a row that produced no text simply fails."""
    if evaluator is None:
        return NO_EVALUATION
    if text is None:
        return Verdict(passed=False)
    return await evaluator.evaluate(text, row)


def build_evaluator(task: TaskConfig, client: ModelClient):
    """The evaluator for a task, or None when it configures no evaluation."""
    evaluation = task.evaluation
    if evaluation is None:
        return None
    if evaluation.type == "script":
        return ScriptEvaluator(evaluation)
    if evaluation.type == "llm_judge":
        return JudgeEvaluator(evaluation, client, task.judge_model)
    return MatchEvaluator(evaluation)


async def _run_command(command: str) -> int | None:
    """The command's exit code, or None when it outran the timeout.

    stdout and stderr are piped and drained so that nothing the command
    prints reaches the tool's own streams or its JSONL output.
    """
    process = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=SCRIPT_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    return process.returncode


def _as_score(extracted: str | None) -> float | int | None:
    """The judge score as a number, keeping whole scores integral."""
    score = as_number(extracted) if extracted is not None else None
    if score is None:
        return None
    return int(score) if score.is_integer() else score


def _matches(extracted: str | None, expected: str) -> bool:
    """Exact-match comparison, treating equal numbers as equal values."""
    if extracted is None:
        return False
    if extracted.strip() == expected.strip():
        return True
    left, right = as_number(extracted), as_number(expected)
    return left is not None and left == right
