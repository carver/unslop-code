"""`llm_judge` evaluation: a second model call that scores a generated response."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rejlib.api import ChatClient
from rejlib.config import JudgeSpec
from rejlib.extraction import extract_answer
from rejlib.prompts import judge_messages

#: A judge reply only scores when the extracted text is a number on its own (T27).
NUMERIC = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class JudgeResult:
    """One judge call: its score, the text ``extract`` took, and its metadata."""

    score: int | float | None
    extracted: str | None
    meta: dict


class Judge:
    """Scores responses with a second API call using the judge prompt."""

    def __init__(self, client: ChatClient, spec: JudgeSpec, extract: str):
        self._client = client
        self._spec = spec
        self._extract = extract

    async def score(self, response: str, row: dict) -> JudgeResult:
        """Ask the judge about one response; an unanswered call yields no score."""
        attempt = await self._client.complete(judge_messages(self._spec, row, response))
        if attempt.content is None:
            return JudgeResult(None, None, attempt.meta)
        extracted = extract_answer(attempt.content, self._extract)
        return JudgeResult(as_score(extracted), extracted, attempt.meta)


def as_score(extracted: str | None) -> int | float | None:
    """The judge's numeric score, ``int`` when the reply reads as a whole number."""
    if extracted is None:
        return None
    text = extracted.strip().replace(",", "")
    if not NUMERIC.fullmatch(text):
        return None
    return float(text) if "." in text else int(text)
