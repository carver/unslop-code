"""Judging a generated response, including the modes that do work of their own.

`exact_match`, `contains` and `regex` are decided from the response text alone
(see `evaluation`). `script` shells out to a command built from the input row,
and `llm_judge` scores the response with a second API call.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from client import ChatClient
from config import EvaluationConfig
from dataset import RESPONSE_FIELD, RenderedPrompt, render
from evaluation import evaluate, extract_answer

#: A judge picks a score rather than writing prose: no sampling, short reply.
JUDGE_TEMPERATURE = 0.0
JUDGE_MAX_TOKENS = 64
SCRIPT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Verdict:
    """The judgement of one response, plus whatever the mode recorded for it."""

    passed: bool | None
    extracted_answer: str | None = None
    judge_score: float | None = None
    judge_meta: dict[str, Any] | None = None


async def evaluate_response(
    config: EvaluationConfig | None, text: str, row: dict[str, Any], client: ChatClient
) -> Verdict:
    """Judge one response, running a script or a judge call if the mode needs it."""
    if config is None:
        return Verdict(passed=None)
    if config.type == "script":
        return await _run_script(config, text, row)
    if config.type == "llm_judge":
        return await _run_judge(config, text, row, client)
    passed, extracted = evaluate(config, text, row)
    return Verdict(passed=passed, extracted_answer=extracted)


async def _run_script(config: EvaluationConfig, text: str, row: dict[str, Any]) -> Verdict:
    """Run the rendered command in a shell; its exit code decides the verdict.

    Output is captured so it stays out of the CLI's own streams, and a command
    that outlives `SCRIPT_TIMEOUT_SECONDS` is killed and counted as a failure.
    """
    command = render(config.command_template, {**row, RESPONSE_FIELD: text})
    # A row field may itself carry the placeholder, e.g. a test snippet that
    # embeds the response; it is only visible once the row has been expanded.
    command = command.replace("{" + RESPONSE_FIELD + "}", text)

    process = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=SCRIPT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return Verdict(passed=False)
    return Verdict(passed=process.returncode == config.success_exit_code)


async def _run_judge(
    config: EvaluationConfig, text: str, row: dict[str, Any], client: ChatClient
) -> Verdict:
    """Score the response with a second API call and compare to the threshold."""
    values = {**row, RESPONSE_FIELD: text}
    prompt = RenderedPrompt(
        system=render(config.judge_prompt.system, values),
        user=render(config.judge_prompt.user, values),
    )
    completion = await client.complete(prompt, JUDGE_TEMPERATURE, JUDGE_MAX_TOKENS, config.model)
    if completion is None:
        return Verdict(passed=False)

    extracted = extract_answer(config.extract, completion.text)
    score = _to_score(extracted)
    return Verdict(
        passed=score is not None and score >= config.threshold,
        extracted_answer=extracted,
        judge_score=score,
        judge_meta=completion.meta,
    )


def _to_score(extracted: str | None) -> float | int | None:
    """Read the judge's answer as a number; an unreadable answer scores nothing."""
    if extracted is None:
        return None
    try:
        score = float(extracted)
    except ValueError:
        return None
    return int(score) if score.is_integer() else score
