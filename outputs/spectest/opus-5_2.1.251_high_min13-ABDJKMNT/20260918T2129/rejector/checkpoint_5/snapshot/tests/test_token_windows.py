"""Unit tests for the sliding-window limiter and the token estimator."""

from __future__ import annotations

import asyncio
import math
import time


from rejector_core import limits
from rejector_core.config import RateLimits


def _run(coro):
    return asyncio.run(coro)


async def _two_oversized(limiter):
    await limiter.reserve(500)
    await limiter.reserve(500)


def _messages(*contents):
    return {"messages": [{"role": "user", "content": text} for text in contents]}


# Spec: "estimate prompt tokens by counting words in the rendered messages
# using `1 token ~= 0.75 words`, rounded up"
def test_prompt_tokens_are_words_over_three_quarters_rounded_up():
    payload = _messages("one two three")
    assert limits.estimate_prompt_tokens(payload) == math.ceil(3 / 0.75)


# Spec: "counting words in the rendered messages" - every message counts,
# not only the user turn
def test_every_message_contributes_words():
    payload = _messages("alpha beta", "gamma delta epsilon")
    assert limits.estimate_prompt_tokens(payload) == math.ceil(5 / 0.75)


# Spec: "the rendered messages" - completions mode renders one prompt string
def test_completions_payloads_are_estimated_from_the_prompt():
    assert limits.estimate_prompt_tokens({"prompt": "a b c d"}) == math.ceil(4 / 0.75)


# Spec: "rounded up" - a word count that is not a multiple of three rounds up
def test_estimate_rounds_up():
    assert limits.estimate_prompt_tokens(_messages("only")) == 2


# Spec: "a tool-call assistant turn carries no content" - null content is
# simply empty text (T84)
def test_messages_without_content_contribute_nothing():
    payload = {"messages": [{"role": "assistant", "content": None}, {"role": "user", "content": "hi"}]}
    assert limits.estimate_prompt_tokens(payload) == 2


# Spec: "continue to enforce RPM, now using a sliding 60-second window"
def test_rpm_window_delays_the_request_past_its_limit(monkeypatch):
    monkeypatch.setattr(limits, "WINDOW_SECONDS", 0.3)
    limiter = limits.RateLimiter(RateLimits(rpm=2), fallback_concurrency=8)

    async def scenario():
        started = time.monotonic()
        for _ in range(3):
            await limiter.reserve(1)
        return time.monotonic() - started

    assert _run(scenario()) >= 0.3


# Spec: "if `rpm` is omitted, RPM limiting is disabled for that task"
def test_no_rpm_means_no_request_pacing(monkeypatch):
    monkeypatch.setattr(limits, "WINDOW_SECONDS", 5.0)
    limiter = limits.RateLimiter(RateLimits(), fallback_concurrency=8)

    async def scenario():
        started = time.monotonic()
        for _ in range(50):
            await limiter.reserve(10_000)
        return time.monotonic() - started

    assert _run(scenario()) < 0.5


# Spec: "when `tpm` is configured, also enforce a sliding 60-second token
# budget"
def test_tpm_window_delays_once_the_token_budget_is_spent(monkeypatch):
    monkeypatch.setattr(limits, "WINDOW_SECONDS", 0.3)
    limiter = limits.RateLimiter(RateLimits(tpm=100), fallback_concurrency=8)

    async def scenario():
        started = time.monotonic()
        await limiter.reserve(60)
        await limiter.reserve(60)
        return time.monotonic() - started

    assert _run(scenario()) >= 0.3


# Spec: "after the response arrives, record actual `prompt_tokens +
# completion_tokens` ... in the TPM window" - settling replaces the
# reservation rather than adding to it (T85)
def test_settling_replaces_the_reservation(monkeypatch):
    monkeypatch.setattr(limits, "WINDOW_SECONDS", 5.0)
    limiter = limits.RateLimiter(RateLimits(tpm=100), fallback_concurrency=8)

    async def scenario():
        reservation = await limiter.reserve(90)
        reservation.settle(10)
        started = time.monotonic()
        await limiter.reserve(80)
        return time.monotonic() - started

    assert _run(scenario()) < 0.2


# Spec: "if both RPM and TPM are configured, a request may be sent only when
# both budgets have capacity"
def test_both_budgets_must_have_capacity(monkeypatch):
    monkeypatch.setattr(limits, "WINDOW_SECONDS", 0.3)
    limiter = limits.RateLimiter(RateLimits(rpm=100, tpm=50), fallback_concurrency=8)

    async def scenario():
        started = time.monotonic()
        await limiter.reserve(40)
        await limiter.reserve(40)
        return time.monotonic() - started

    assert _run(scenario()) >= 0.3


# Spec: a reservation larger than the whole budget still goes out once the
# window empties instead of hanging forever (T104)
def test_a_reservation_larger_than_the_budget_still_proceeds(monkeypatch):
    monkeypatch.setattr(limits, "WINDOW_SECONDS", 0.2)
    limiter = limits.RateLimiter(RateLimits(tpm=10), fallback_concurrency=8)

    async def scenario():
        await asyncio.wait_for(_two_oversized(limiter), timeout=5)
        return True

    assert _run(scenario())


# Spec: "`max_concurrent` is a hard cap on in-flight requests independent of
# RPM and TPM"
def test_slots_cap_simultaneous_holders():
    limiter = limits.RateLimiter(RateLimits(max_concurrent=2), fallback_concurrency=64)
    peak = 0
    held = 0

    async def hold():
        nonlocal peak, held
        async with limiter.slot():
            held += 1
            peak = max(peak, held)
            await asyncio.sleep(0.05)
            held -= 1

    async def scenario():
        await asyncio.gather(*(hold() for _ in range(8)))

    _run(scenario())
    assert peak == 2


# Spec: "`max_concurrent` is a hard cap" - with the key absent the earlier
# rpm-derived budget stands in (T83)
def test_absent_max_concurrent_uses_the_fallback_budget():
    limiter = limits.RateLimiter(RateLimits(rpm=100), fallback_concurrency=3)
    peak = 0
    held = 0

    async def hold():
        nonlocal peak, held
        async with limiter.slot():
            held += 1
            peak = max(peak, held)
            await asyncio.sleep(0.05)
            held -= 1

    async def scenario():
        await asyncio.gather(*(hold() for _ in range(8)))

    _run(scenario())
    assert peak == 3
