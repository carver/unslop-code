"""The `llm_judge` evaluation: a second API call that scores a response."""

from __future__ import annotations

from .api import Channel
from .config import EvaluationConfig
from .evaluation import Verdict, extract_answer
from .inputs import render_judge_messages

JUDGE_TEMPERATURE = 0.0


async def judge_response(
    text: str, evaluation: EvaluationConfig, row: dict, channel: Channel
) -> Verdict:
    """Ask the judge model to score `text`, then compare it to the threshold.

    A judge call that fails, or answers with no number, leaves nothing to
    compare, so the row fails.
    """
    judge = evaluation.judge
    messages = render_judge_messages(judge, row, text)
    completion = await channel.client.complete(
        messages, JUDGE_TEMPERATURE, channel.judge
    )
    if completion is None:
        return Verdict(passed=False)

    score = _score(extract_answer(completion.content, evaluation.extract))
    return Verdict(
        passed=score is not None and score >= judge.threshold,
        judge_score=score,
        judge_meta=completion.meta,
    )


def _score(extracted: str | None) -> float | int | None:
    """The judge's numeric score, as an int when it is a whole number."""
    if extracted is None:
        return None
    try:
        return int(extracted)
    except ValueError:
        pass
    try:
        return float(extracted)
    except ValueError:
        return None
