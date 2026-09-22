"""Token-aware scheduling: prompt estimation, sliding windows, and the concurrency cap."""

import asyncio

import httpx
import pytest

from config import RateLimits, load_config
from helpers import load_multi
from ratelimit import RateLimiter, estimate_prompt_tokens

#: Long enough for an unblocked reservation, short enough that a blocked one times out.
MOMENT = 0.05



def limits_config(url, *, rate_limits):
    """A task config whose ``rate_limits`` block is spelled out by the caller."""
    return f"""
task:
  name: "paced"
  api_url: "{url}"
  model: "mock-model"
  rate_limits:
{rate_limits}
  prompt:
    user: "{{question}}"
  generation:
    scheme: "greedy"
    max_tokens: 32
  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
  output_field: "solution"
"""


def rows(count):
    return [{"question": f"question {index}", "answer": "8"} for index in range(count)]


def peak_in_flight(server):
    """The most requests the mock server ever had in flight at once."""
    return httpx.get(server.url).json()["peak"]


def reserve_soon(limiter, tokens):
    """One reservation, giving up if the limiter holds it back."""
    return asyncio.wait_for(limiter.reserve(tokens), MOMENT)


def test_prompt_tokens_are_estimated_from_word_count():
    messages = [{"role": "system", "content": "one two three"}, {"role": "user", "content": "four"}]

    assert estimate_prompt_tokens(messages) == 6
    assert estimate_prompt_tokens([{"role": "user", "content": None}]) == 0


def test_a_spent_token_budget_holds_the_next_request_back():
    async def scenario():
        limiter = RateLimiter(RateLimits(tpm=100))
        await reserve_soon(limiter, 100)
        with pytest.raises(asyncio.TimeoutError):
            await reserve_soon(limiter, 50)

    asyncio.run(scenario())


def test_a_spent_request_budget_holds_the_next_request_back():
    async def scenario():
        limiter = RateLimiter(RateLimits(rpm=1))
        await reserve_soon(limiter, 1)
        with pytest.raises(asyncio.TimeoutError):
            await reserve_soon(limiter, 1)

    asyncio.run(scenario())


def test_unset_budgets_never_hold_a_request_back():
    async def scenario():
        limiter = RateLimiter(RateLimits())
        for _ in range(50):
            await reserve_soon(limiter, 10_000)

    asyncio.run(scenario())


def test_a_request_larger_than_the_whole_budget_still_runs():
    async def scenario():
        await reserve_soon(RateLimiter(RateLimits(tpm=10)), 1000)

    asyncio.run(scenario())


def test_settling_a_reservation_frees_the_unused_estimate():
    async def scenario():
        limiter = RateLimiter(RateLimits(tpm=100))
        reservation = await reserve_soon(limiter, 90)
        with pytest.raises(asyncio.TimeoutError):
            await reserve_soon(limiter, 90)
        reservation.settle(5)
        await reserve_soon(limiter, 90)

    asyncio.run(scenario())


def test_max_concurrent_caps_requests_in_flight(mock_server, run_cli):
    server = mock_server("--latency", "0.2", "--capacity", "16")
    config = limits_config(server.url, rate_limits="    rpm: 600\n    max_concurrent: 2\n")

    completed, summary, results = run_cli(config, rows(8))

    assert completed.returncode == 0, completed.stderr
    assert len(results) == 8 and summary["passed"] == 8
    assert peak_in_flight(server) <= 2


def test_without_a_cap_requests_overlap(mock_server, run_cli):
    server = mock_server("--latency", "0.2", "--capacity", "16")
    config = limits_config(server.url, rate_limits="    rpm: 600\n")

    completed, _, results = run_cli(config, rows(8))

    assert completed.returncode == 0, completed.stderr
    assert len(results) == 8
    assert peak_in_flight(server) > 2


def test_a_token_budget_that_fits_the_run_does_not_hold_it_up(mock_server, run_cli):
    server = mock_server()
    config = limits_config(server.url, rate_limits="    rpm: 600\n    tpm: 100000\n")

    completed, summary, results = run_cli(config, rows(4))

    assert completed.returncode == 0, completed.stderr
    assert len(results) == 4
    assert summary["elapsed_seconds"] < 5


def test_omitting_rpm_disables_request_limiting(mock_server, run_cli):
    server = mock_server()
    config = limits_config(server.url, rate_limits="    tpm: 100000\n")

    completed, _, results = run_cli(config, rows(4))

    assert completed.returncode == 0, completed.stderr
    assert len(results) == 4


def test_cli_flags_override_the_configured_limits(mock_server, run_cli):
    server = mock_server("--latency", "0.2", "--capacity", "16")
    config = limits_config(server.url, rate_limits="    rpm: 600\n    max_concurrent: 8\n")

    completed, _, results = run_cli(config, rows(6), "--max-concurrent", "1", "--tpm", "100000")

    assert completed.returncode == 0, completed.stderr
    assert len(results) == 6
    assert peak_in_flight(server) == 1


def test_per_task_rate_limits_override_only_the_keys_they_name(tmp_path):
    tasks = load_multi(tmp_path)

    assert tasks["gsm8k"].limits == RateLimits(rpm=100, tpm=50000, max_concurrent=10)
    assert tasks["code_gen"].limits == RateLimits(rpm=100, tpm=30000, max_concurrent=10)


def test_limit_flags_win_over_every_task(tmp_path):
    tasks = load_multi(tmp_path, {"rpm": 7, "tpm": 8, "max_concurrent": 9})

    assert [task.limits for task in tasks.values()] == [RateLimits(7, 8, 9)] * 2


def test_a_top_level_rpm_still_sets_the_request_budget(tmp_path):
    path = tmp_path / "task.yaml"
    path.write_text(
        'task:\n  api_url: "http://example.invalid"\n  model: "m"\n  rpm: 42\n'
        '  output_field: "solution"\n  prompt:\n    user: "{question}"\n',
        encoding="utf-8",
    )

    config = load_config(str(path), {})

    assert config.tasks[0].limits == RateLimits(rpm=42)
