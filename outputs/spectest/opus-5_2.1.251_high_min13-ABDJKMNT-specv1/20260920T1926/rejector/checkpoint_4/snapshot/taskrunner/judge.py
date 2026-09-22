"""`llm_judge` evaluation: the second model call that scores a response."""

from __future__ import annotations

from typing import Any, Mapping

from .api import CallResult, ModelClient
from .config import JudgeConfig
from .prompts import RESPONSE_FIELD, render_messages

# The judge classifies rather than writes, so it always runs deterministically.
JUDGE_TEMPERATURE = 0.0


async def ask_judge(
    client: ModelClient, config: JudgeConfig, row: Mapping[str, Any], response: str
) -> CallResult:
    """Send the judge prompt, rendered from the row plus the generated response."""
    messages = render_messages(config.prompt, {**row, RESPONSE_FIELD: response})
    return await client.complete(messages, JUDGE_TEMPERATURE)


def to_score(text: str | None) -> float | None:
    """The judge's score, or `None` when the extracted text is not a number."""
    if text is None:
        return None
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return None
