"""`llm_judge` evaluation: score a response with a second model call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api import ApiClient
from config import TaskConfig
from evaluation import EXTRACTORS, LLM_JUDGE, NUMBER_PATTERN, EvaluationConfig, Outcome
from templates import RESPONSE, render

#: Judging is a rating, not a generation, so it is always asked for deterministically.
JUDGE_TEMPERATURE = 0.0


@dataclass(frozen=True)
class Judge:
    """Rates responses with the judge model configured for one task.

    The call goes through the task's own client, so it is paced by the same
    rate limiter and counted in the same API call total as the generations.
    """

    client: ApiClient
    config: EvaluationConfig
    max_tokens: int

    async def score(self, text: str, row: dict[str, Any]) -> Outcome:
        """Ask the judge to rate `text`; it passes when the score reaches the threshold."""
        messages = render(self.config.judge_prompt, {**row, RESPONSE: text})
        completion = await self.client.complete(messages, self.config.model, JUDGE_TEMPERATURE, self.max_tokens)
        if completion is None:
            return Outcome(passed=False, extracted=None)

        extracted = EXTRACTORS[self.config.extract](completion.text)
        score = _as_score(extracted)
        return Outcome(
            passed=score is not None and score >= self.config.threshold,
            extracted=extracted,
            judge_score=score,
            judge_meta=completion.meta,
        )


def build_judge(task: TaskConfig, client: ApiClient) -> Judge | None:
    """A judge for tasks evaluated by `llm_judge`, None for every other task."""
    if task.evaluation is None or task.evaluation.type != LLM_JUDGE:
        return None
    return Judge(client=client, config=task.evaluation, max_tokens=task.generation.max_tokens)


def _as_score(extracted: str | None) -> float | int | None:
    """The extracted rating as a number, kept an int when the judge gave a whole one."""
    if extracted is None or not NUMBER_PATTERN.fullmatch(extracted.strip()):
        return None
    value = float(extracted)
    return int(value) if value.is_integer() else value
