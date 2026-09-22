"""Retry handling, request shaping and the billing of a finished call."""

import asyncio
import json

import httpx
import pytest

from api import MAX_RETRIES, ApiClient
from cost import CostConfig, CostTracker
from endpoints import ChatEndpoint
from limits import RateLimits, RequestLimiter
from tracking import RunMetrics

MESSAGES = [{"role": "user", "content": "2 + 3?"}]

COMPLETION = {
    "id": "chatcmpl-1",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "#### 5"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
}


def client_for(*statuses, capture=None, metrics=None, cost=None):
    """An ApiClient whose transport replies with `statuses` in order (repeating the last)."""
    codes = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        status = codes.pop(0) if len(codes) > 1 else codes[0]
        return httpx.Response(status, json=COMPLETION if status == 200 else {"error": "boom"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://api")
    limiter = RequestLimiter(RateLimits(rpm=6000))
    return ApiClient(http, limiter, metrics or RunMetrics(CostTracker()), ChatEndpoint(), cost)


def test_successful_call_builds_metadata():
    metrics = RunMetrics(CostTracker())
    client = client_for(200, metrics=metrics)
    completion = asyncio.run(client.complete(MESSAGES, "gpt-4", 0.0, 128))
    latency_ms = completion.meta.pop("latency_ms")
    assert completion.text == "#### 5"
    assert completion.meta == {
        "model": "gpt-4",
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
        "finish_reason": "stop",
    }
    assert latency_ms >= 0
    assert (client.api_calls, metrics.timeline.elapsed_seconds > 0) == (1, True)


def test_request_payload_matches_the_api_contract():
    requests = []
    client = client_for(200, capture=requests)
    asyncio.run(client.complete(MESSAGES, "gpt-4", 0.7, 256))
    assert requests[0].url.path == "/v1/chat/completions"
    assert json.loads(requests[0].content) == {
        "model": "gpt-4",
        "messages": MESSAGES,
        "temperature": 0.7,
        "max_tokens": 256,
    }


def test_server_errors_are_retried_then_succeed():
    client = client_for(503, 500, 200)
    assert asyncio.run(client.complete(MESSAGES, "gpt-4", 0.0, 128)).text == "#### 5"
    assert client.api_calls == 3


def test_row_is_given_up_on_after_the_retry_budget():
    client = client_for(500)
    assert asyncio.run(client.complete(MESSAGES, "gpt-4", 0.0, 128)) is None
    assert client.api_calls == MAX_RETRIES + 1


def test_client_errors_are_not_retried():
    client = client_for(400)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.complete(MESSAGES, "gpt-4", 0.0, 128))
    assert client.api_calls == 1


def test_a_finished_call_is_billed_to_the_run():
    metrics = RunMetrics(CostTracker(configured=True))
    client = client_for(200, metrics=metrics, cost=CostConfig(prompt_per_1k=1.0, completion_per_1k=2.0))
    asyncio.run(client.complete(MESSAGES, "gpt-4", 0.0, 128))

    # 7 prompt tokens at $1/1k and 3 completion tokens at $2/1k.
    assert (round(metrics.cost.prompt, 6), round(metrics.cost.completion, 6)) == (0.007, 0.006)


def test_an_exhausted_budget_sends_nothing():
    metrics = RunMetrics(CostTracker(budget=0.5, configured=True))
    metrics.cost.prompt = 0.5
    client = client_for(200, metrics=metrics)

    assert asyncio.run(client.complete(MESSAGES, "gpt-4", 0.0, 128)) is None
    assert client.api_calls == 0
