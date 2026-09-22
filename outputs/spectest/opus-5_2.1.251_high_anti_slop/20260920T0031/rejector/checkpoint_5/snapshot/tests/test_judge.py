"""Judge prompt rendering, score extraction and the threshold."""

import asyncio

import pytest

from endpoints import Completion
from evaluation import EvaluationConfig
from judge import Judge
from templates import PromptConfig

ROW = {"prompt_text": "write a haiku", "criteria": "imagery"}
META = {"model": "judge-model", "prompt_tokens": 12, "completion_tokens": 1, "total_tokens": 13}

CONFIG = EvaluationConfig(
    type="llm_judge",
    extract="first_number",
    judge_prompt=PromptConfig(
        system="Respond with an integer.",
        user="Rate this response to {prompt_text}:\n{__response__}\n\nCriteria: {criteria}",
    ),
    threshold=7,
    model="judge-model",
)


class StubClient:
    """Answers with prepared judge replies and records what it was asked."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    async def complete(self, messages, model, temperature, max_tokens):
        self.requests.append((messages, model, temperature, max_tokens))
        return self.responses.pop(0)


def score(*responses, config=CONFIG):
    client = StubClient(*responses)
    return client, asyncio.run(Judge(client, config, max_tokens=32).score("a fine haiku", ROW))


def test_judge_prompt_carries_the_response_and_row_fields():
    client, _ = score(Completion("8", META))
    messages, model, temperature, max_tokens = client.requests[0]
    assert messages == [
        {"role": "system", "content": "Respond with an integer."},
        {"role": "user", "content": "Rate this response to write a haiku:\na fine haiku\n\nCriteria: imagery"},
    ]
    assert (model, temperature, max_tokens) == ("judge-model", 0.0, 32)


def test_score_at_the_threshold_passes_and_is_recorded():
    _, outcome = score(Completion("8", META))
    assert (outcome.passed, outcome.judge_score, outcome.extracted) == (True, 8, "8")
    assert outcome.judge_meta == META


@pytest.mark.parametrize("reply, expected", [("6", False), ("7", True), ("Score: 9 out of 10", True)])
def test_threshold_decides_the_row(reply, expected):
    assert score(Completion(reply, META))[1].passed is expected


def test_fractional_scores_keep_their_decimals():
    outcome = score(Completion("7.5", META), config=CONFIG)[1]
    assert (outcome.judge_score, outcome.passed) == (7.5, True)


def test_unparsable_judge_reply_fails_the_row():
    outcome = score(Completion("excellent", META))[1]
    assert (outcome.passed, outcome.judge_score) == (False, None)


def test_failed_judge_call_fails_the_row():
    outcome = score(None)[1]
    assert (outcome.passed, outcome.judge_meta) == (False, None)
