"""Sliding window request and token budgets, and the concurrency cap."""

import asyncio
import time

import pytest
import yaml

from config import RateLimits, load_config
from limits import Limiter, estimate_tokens

TASK = {
    "name": "math_solve",
    "model": "gpt-4",
    "prompt": {"user": "{question}"},
    "generation": {"scheme": "greedy", "max_tokens": 64},
    "output_field": "solution",
}


@pytest.fixture
def window(monkeypatch):
    """Shrink the sliding window so the budgets can be watched in real time."""
    monkeypatch.setattr("limits.WINDOW_SECONDS", 0.4)
    return 0.4


def limits(rpm=None, tpm=None, max_concurrent=10):
    return RateLimits(rpm=rpm, tpm=tpm, max_concurrent=max_concurrent)


async def reserve_all(limiter, requests):
    """Reserve each request in turn, returning the seconds each one waited."""
    started = time.monotonic()
    marks = []
    for tokens in requests:
        await limiter.reserve(tokens)
        marks.append(time.monotonic() - started)
    return marks


def test_prompt_tokens_are_estimated_from_word_count():
    messages = [{"role": "system", "content": "one two three"}, {"role": "user", "content": "four"}]
    # Four words at 0.75 words per token, rounded up.
    assert estimate_tokens(messages) == 6


def test_a_message_without_content_contributes_nothing():
    assert estimate_tokens([{"role": "assistant", "content": None}]) == 0


def test_requests_wait_for_the_request_window_to_slide(window):
    limiter = Limiter(limits(rpm=2))
    marks = asyncio.run(reserve_all(limiter, [1, 1, 1]))

    assert marks[1] < window / 2
    assert marks[2] >= window


def test_requests_wait_for_the_token_window_to_slide(window):
    limiter = Limiter(limits(tpm=1000))
    marks = asyncio.run(reserve_all(limiter, [600, 600]))

    assert marks[1] >= window


def test_a_settled_reservation_frees_the_tokens_it_did_not_use(window):
    async def scenario():
        limiter = Limiter(limits(tpm=1000))
        reservation = await limiter.reserve(600)
        reservation.settle(10)
        return await reserve_all(limiter, [600])

    # The estimate reserved 600 of the 1000, but the call only used 10 of them.
    assert asyncio.run(scenario())[0] < window / 2


def test_the_tighter_of_the_two_budgets_binds(window):
    limiter = Limiter(limits(rpm=100, tpm=1000))
    marks = asyncio.run(reserve_all(limiter, [900, 900]))

    # The request budget has plenty of room left; the token budget does not.
    assert marks[1] >= window


def test_an_omitted_budget_is_not_enforced(window):
    limiter = Limiter(limits())
    marks = asyncio.run(reserve_all(limiter, [10_000] * 5))

    assert max(marks) < window / 2


def test_max_concurrent_caps_the_requests_in_flight(cli, api):
    rows = [{"question": f"q{index}"} for index in range(8)]
    url, _ = api(lambda payload, call: "#### 5", delay=0.2, capacity=8)
    started = time.monotonic()
    run = cli({**TASK, "api_url": url, "rate_limits": {"max_concurrent": 2}}, rows)
    elapsed = time.monotonic() - started

    # Two at a time through eight requests of 0.2s each: four rounds.
    assert run.code == 0 and len(run.records) == 8
    assert elapsed >= 0.8


def test_the_request_budget_paces_a_whole_run(cli, api, window):
    rows = [{"question": f"q{index}"} for index in range(6)]
    url, _ = api(lambda payload, call: "#### 5")
    started = time.monotonic()
    run = cli({**TASK, "api_url": url, "rate_limits": {"rpm": 2}}, rows)

    # Two requests per window, so the last pair waits out two windows.
    assert time.monotonic() - started >= 2 * window
    assert run.summary["total_api_calls"] == 6


def test_the_token_budget_paces_a_whole_run(cli, api, window):
    rows = [{"question": f"q{index}"} for index in range(4)]
    url, _ = api(lambda payload, call: "#### 5")
    started = time.monotonic()
    # Each request reserves its prompt plus the 64 token completion, so only one
    # of them fits in a 100 token minute.
    run = cli({**TASK, "api_url": url, "rate_limits": {"rpm": 600, "tpm": 100}}, rows)

    assert time.monotonic() - started >= 2 * window
    assert run.summary["total_api_calls"] == 4


def test_rate_limits_merge_into_each_task_of_a_multi_config(tmp_path):
    document = {
        "defaults": {
            "api_url": "http://localhost:8000",
            "model": "gpt-4",
            "rate_limits": {"rpm": 100, "tpm": 50000, "max_concurrent": 10},
        },
        "tasks": {
            "code_gen": {
                "prompt": {"user": "{problem}"},
                "generation": {"scheme": "greedy"},
                "output_field": "code",
                "rate_limits": {"tpm": 30000},
            },
            "gsm8k": {
                "prompt": {"user": "{question}"},
                "generation": {"scheme": "greedy"},
                "output_field": "solution",
            },
        },
    }
    path = tmp_path / "multi.yaml"
    path.write_text(yaml.safe_dump(document))
    code_gen, gsm8k = load_config(path, {}).tasks

    assert code_gen.rate_limits == RateLimits(rpm=100, tpm=30000, max_concurrent=10)
    assert gsm8k.rate_limits == RateLimits(rpm=100, tpm=50000, max_concurrent=10)


def test_cli_flags_override_the_configured_limits(tmp_path):
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": {**TASK, "api_url": "http://x", "rpm": 60}}))
    config = load_config(path, {"tpm": 1234, "max_concurrent": 3}).tasks[0]

    assert config.rate_limits == RateLimits(rpm=60, tpm=1234, max_concurrent=3)
