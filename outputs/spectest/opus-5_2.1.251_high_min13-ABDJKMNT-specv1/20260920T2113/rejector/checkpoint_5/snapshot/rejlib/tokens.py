"""Word-based token estimation used to schedule and to forecast requests.

Two estimators live here because the spec states two: the scheduler counts words
in the rendered request (``1 token ~= 0.75 words``) to reserve TPM budget before
dispatch, and the dry-run estimator scales the average prompt word count by
``1.33``.
"""

from __future__ import annotations

import math

#: "estimate prompt tokens by counting words in the rendered messages using
#: `1 token ~= 0.75 words`, rounded up"
WORDS_PER_TOKEN = 0.75

#: "estimate prompt tokens as `average prompt word count * 1.33`"
DRY_RUN_TOKENS_PER_WORD = 1.33


def count_words(text: str) -> int:
    """Whitespace-separated words in one piece of rendered prompt text."""
    return len(text.split())


def estimate_tokens(words: int) -> int:
    """The scheduler's prompt-token estimate for a word count, rounded up."""
    return math.ceil(words / WORDS_PER_TOKEN)


def payload_words(payload: dict) -> int:
    """Words in a request body: the message contents, or the rendered prompt (T91)."""
    if "prompt" in payload:
        return count_words(payload["prompt"])
    return sum(count_words(message.get("content") or "") for message in payload["messages"])


def dry_run_tokens(average_words: float) -> float:
    """The dry-run prompt-token estimate for one request, kept unrounded (T85)."""
    return average_words * DRY_RUN_TOKENS_PER_WORD
