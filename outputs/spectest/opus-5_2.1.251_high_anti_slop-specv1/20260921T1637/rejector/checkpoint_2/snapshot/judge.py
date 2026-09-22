"""LLM-as-judge evaluation: a second model scores the response and the score is thresholded."""

from dataclasses import dataclass
from typing import Any

from api import ChatClient
from config import EvaluationConfig
from dataset import RESPONSE_KEY, render_messages
from extraction import as_number, extract_answer
from results import CallMeta

#: A judge reply is a short verdict, so it is deterministic and needs few tokens.
JUDGE_TEMPERATURE = 0.0
JUDGE_MAX_TOKENS = 256


@dataclass(frozen=True)
class JudgeVerdict:
    """What one judge call decided, plus the metadata of the call itself."""

    passed: bool
    score: float | int | None
    extracted: str | None
    meta: CallMeta


async def judge_response(
    client: ChatClient, config: EvaluationConfig, text: str, row: dict[str, Any]
) -> JudgeVerdict:
    """Ask the judge model to score ``text`` and compare that score against the threshold."""
    messages = render_messages(
        config.judge_prompt, {**row, RESPONSE_KEY: text}, "judge prompt template"
    )
    completion = await client.complete(messages, JUDGE_TEMPERATURE, JUDGE_MAX_TOKENS)
    if completion.text is None:
        return JudgeVerdict(passed=False, score=None, extracted=None, meta=completion.meta)

    extracted = extract_answer(config.extract, completion.text)
    score = as_number(extracted)
    return JudgeVerdict(
        passed=score is not None and score >= config.threshold,
        score=_plain(score),
        extracted=extracted,
        meta=completion.meta,
    )


def _plain(score: float | None) -> float | int | None:
    """Report a whole score as an int, so ``judge_score`` reads ``8`` rather than ``8.0``."""
    if score is None or not score.is_integer():
        return score
    return int(score)
