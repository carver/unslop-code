"""Token-aware scheduling: the sliding RPM/TPM windows and `max_concurrent`.

The windows are 60 seconds wide, so the unit tests shrink
`limits.WINDOW_SECONDS` and watch how long an admission takes instead of
waiting a minute for one to slide.
"""

from __future__ import annotations

import asyncio
import time

import aiohttp
import pytest
import yaml

from conftest import agentic_config, make_config
from mock_server import Reply
from rejector_lib import limits
from rejector_lib.agentic import run_loop
from rejector_lib.api import ChatClient
from rejector_lib.config import Overrides, load_config
from rejector_lib.cost import CostTracker
from rejector_lib.limits import RateLimiter, RateLimits, estimate_prompt_tokens
from rejector_lib.runner import open_channel

WINDOW = 0.4


@pytest.fixture
def short_window(monkeypatch):
    """Shrink the sliding window so a blocked admission is observable."""
    monkeypatch.setattr(limits, "WINDOW_SECONDS", WINDOW)
    return WINDOW


def timed(scenario) -> float:
    """Run one async scenario and return how long it took, in seconds."""
    started = time.monotonic()
    asyncio.run(scenario())
    return time.monotonic() - started


def questions(count: int) -> list[dict]:
    return [{"question": f"q{index}", "answer": str(index)} for index in range(count)]


def echo_index(payload, path, index) -> Reply:
    """Answer each row with its own number, so outputs can be paired back."""
    return Reply(content=f"#### {_question(payload)[1:]}")


def _question(payload: dict) -> str:
    """The row's own question, which is the first user turn of the request."""
    return next(m["content"] for m in payload["messages"] if m["role"] == "user")


# Spec: "continue to enforce RPM, now using a sliding 60-second window" -- a
# full window's worth of requests goes out at once, and the next one waits for
# the oldest to age out.
def test_rpm_admits_a_full_window_then_waits(short_window):
    async def scenario():
        limiter = RateLimiter(RateLimits(rpm=3))
        for _ in range(3):
            await limiter.reserve(10)

    assert timed(scenario) < WINDOW / 2

    async def scenario_with_one_more():
        limiter = RateLimiter(RateLimits(rpm=3))
        for _ in range(4):
            await limiter.reserve(10)

    assert timed(scenario_with_one_more) >= short_window


# Spec: "if `rpm` is omitted, RPM limiting is disabled for that task".
def test_rpm_omitted_disables_request_limiting(short_window):
    async def scenario():
        limiter = RateLimiter(RateLimits())
        for _ in range(50):
            await limiter.reserve(10_000)

    assert timed(scenario) < WINDOW / 2


# Spec: "when `tpm` is configured, also enforce a sliding 60-second token
# budget" -- two 600-token requests do not fit in a 1000-token minute.
def test_tpm_blocks_a_request_that_does_not_fit(short_window):
    async def scenario():
        limiter = RateLimiter(RateLimits(tpm=1000))
        await limiter.reserve(600)
        await limiter.reserve(600)

    assert timed(scenario) >= short_window


# Spec: "after the response arrives, record actual `prompt_tokens +
# completion_tokens` from the API response in the TPM window" -- the recorded
# total replaces the reservation, so unused reserved tokens come back. (T84)
def test_recorded_usage_replaces_the_reservation(short_window):
    async def scenario():
        limiter = RateLimiter(RateLimits(tpm=1000))
        reservation = await limiter.reserve(600)
        limiter.record(reservation, 100)
        await limiter.reserve(600)

    assert timed(scenario) < WINDOW / 2


# Spec: "if both RPM and TPM are configured, a request may be sent only when
# both budgets have capacity" -- here RPM has room and TPM does not.
def test_tpm_binds_even_when_rpm_has_room(short_window):
    async def scenario():
        limiter = RateLimiter(RateLimits(rpm=100, tpm=1000))
        await limiter.reserve(900)
        await limiter.reserve(900)

    assert timed(scenario) >= short_window


# Spec: the same rule the other way round -- TPM has room and RPM does not.
def test_rpm_binds_even_when_tpm_has_room(short_window):
    async def scenario():
        limiter = RateLimiter(RateLimits(rpm=1, tpm=1_000_000))
        await limiter.reserve(10)
        await limiter.reserve(10)

    assert timed(scenario) >= short_window


# Spec: "`max_concurrent` is a hard cap on in-flight requests independent of
# RPM and TPM" -- a third slot is only free once one is released.
def test_max_concurrent_caps_in_flight_requests(short_window):
    async def scenario():
        limiter = RateLimiter(RateLimits(max_concurrent=2))
        await limiter.slots.acquire()
        await limiter.slots.acquire()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(limiter.slots.acquire(), timeout=0.2)
        limiter.slots.release()
        await asyncio.wait_for(limiter.slots.acquire(), timeout=0.5)

    asyncio.run(scenario())


# Spec: "estimate prompt tokens by counting words in the rendered messages
# using `1 token ~= 0.75 words`, rounded up". (T82, T83)
def test_prompt_token_estimate_rounds_words_up():
    assert estimate_prompt_tokens(["one two three"]) == 4
    assert estimate_prompt_tokens(["one two", "three four"]) == 6
    assert estimate_prompt_tokens([""]) == 0


# Spec: "`max_concurrent` is a hard cap on in-flight requests" -- the server
# never sees more than the configured number at once.
def test_max_concurrent_caps_requests_at_the_server(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.1, workers=8)
    config = make_config(server.url, rate_limits={"max_concurrent": 3})
    result = run_cli(config, questions(12))
    assert result.exit_code == 0, result.stderr
    assert len(result.rows) == 12
    assert server.peak_concurrency <= 3


# Spec: "each `llm_judge` call goes through the same limiter".
def test_judge_calls_share_the_concurrency_cap(servers, run_cli):
    server = servers(
        contents=["an answer"], content_if_contains={"judge": "9"}, service_time=0.05
    )
    config = make_config(
        server.url,
        rate_limits={"max_concurrent": 1},
        prompt={"user": "{question}"},
        evaluation={
            "type": "llm_judge",
            "judge_prompt": {"system": "judge", "user": "Score {__response__}"},
            "threshold": 7,
        },
    )
    result = run_cli(config, questions(4))
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 8
    assert server.peak_concurrency == 1


# Spec: "for agentic loops, every API request counts toward RPM and TPM, and
# the loop holds one concurrency slot for its entire lifetime" -- with a single
# slot, one loop's requests never interleave with another's.
def test_agentic_loop_holds_its_slot_for_the_whole_loop(servers, run_cli):
    lookup = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "employees"}}])
    server = servers(
        responder=lambda payload, path, index: (
            Reply(content="142 employees") if _turns(payload) else lookup
        ),
        service_time=0.05,
    )
    config = agentic_config(server.url, rate_limits={"max_concurrent": 1})
    rows = [{"question": f"q{i}", "answer": "142"} for i in range(3)]
    result = run_cli(config, rows)
    assert result.exit_code == 0, result.stderr
    assert server.peak_concurrency == 1
    asked = [_question(payload) for payload in server.payloads]
    assert asked == ["q0", "q0", "q1", "q1", "q2", "q2"]


def _turns(payload: dict) -> int:
    return sum(1 for message in payload["messages"] if message.get("tool_calls"))


# Spec: "rows are still paired with outputs in input order even when requests
# overlap; concurrent execution must not cause a later input row to consume the
# response intended for an earlier row."
def test_rows_keep_their_own_responses_when_requests_overlap(servers, run_cli):
    def slow_first(payload, path, index):
        if _question(payload) == "q0":
            time.sleep(0.4)
        return echo_index(payload, path, index)

    server = servers(responder=slow_first, workers=8)
    config = make_config(server.url, rate_limits={"max_concurrent": 8})
    result = run_cli(config, questions(6))
    assert result.exit_code == 0, result.stderr
    outputs = [row["output"]["solution"] for row in result.rows]
    assert outputs == [f"#### {index}" for index in range(6)]
    assert all(row["result"]["passed"] for row in result.rows)


# Spec: "for agentic loops, every API request counts toward RPM and TPM" --
# driven in-process so the sliding window can be shrunk: at one request per
# window, a two-iteration loop cannot finish inside one window.
def test_agentic_iterations_count_against_rpm(servers, tmp_path, short_window):
    lookup = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "employees"}}])
    server = servers(
        responder=lambda payload, path, index: (
            Reply(content="142 employees") if _turns(payload) else lookup
        )
    )
    task = _task_config(
        tmp_path, agentic_config(server.url, rate_limits={"rpm": 1})
    )

    async def scenario():
        async with aiohttp.ClientSession() as session:
            channel = open_channel(task, ChatClient(session, CostTracker()))
            run = await run_loop({"question": "q0", "answer": "142"}, task, channel)
            assert run.iterations == 2

    assert timed(scenario) >= short_window


def _task_config(tmp_path, config: dict):
    """Write a config file and build the single task it declares."""
    path = tmp_path / "agentic.yaml"
    path.write_text(yaml.safe_dump(config))
    raw = load_config(path)
    return raw.build(next(iter(raw.tasks)), Overrides())
