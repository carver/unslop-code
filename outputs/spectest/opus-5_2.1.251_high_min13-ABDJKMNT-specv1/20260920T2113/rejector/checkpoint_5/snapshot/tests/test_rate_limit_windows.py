"""The sliding 60-second request and token budgets, and the token estimate."""

from __future__ import annotations

import asyncio

import pytest

from rejlib.ratelimit import WINDOW, Concurrency, RateLimiter
from rejlib.tokens import estimate_tokens, payload_words


# "continue to enforce RPM, now using a sliding 60-second window"
def test_requests_are_admitted_until_the_window_is_full():
    limiter = RateLimiter(rpm=3)
    for moment in (0.0, 0.1, 0.2):
        assert limiter.delay(moment, 0) == 0.0
        limiter.admit(moment, 0)
    assert limiter.delay(0.3, 0) > 0


# "a sliding 60-second window" - capacity returns as the oldest request ages out,
# not on a fixed boundary
def test_window_slides_with_the_oldest_request():
    limiter = RateLimiter(rpm=2)
    limiter.admit(0.0, 0)
    limiter.admit(10.0, 0)
    assert limiter.delay(30.0, 0) == pytest.approx(WINDOW - 30.0)
    assert limiter.delay(60.5, 0) == 0.0


# "a sliding 60-second window" - a request older than the window is forgotten
def test_requests_outside_the_window_free_capacity():
    limiter = RateLimiter(rpm=1)
    limiter.admit(0.0, 0)
    assert limiter.delay(59.0, 0) == pytest.approx(1.0)
    assert limiter.delay(61.0, 0) == 0.0


# "if `rpm` is omitted, RPM limiting is disabled for that task"
def test_no_rpm_means_no_request_delay():
    limiter = RateLimiter(rpm=None)
    for index in range(100):
        limiter.admit(0.0, 0)
    assert limiter.delay(0.0, 0) == 0.0


# "when `tpm` is configured, also enforce a sliding 60-second token budget"
def test_token_budget_delays_a_request_that_does_not_fit():
    limiter = RateLimiter(tpm=1000)
    limiter.admit(0.0, 600)
    assert limiter.delay(0.0, 300) == 0.0
    assert limiter.delay(0.0, 600) == pytest.approx(WINDOW)


# "when `tpm` is configured" - tokens age out of the window like requests do
def test_token_budget_recovers_after_the_window():
    limiter = RateLimiter(tpm=1000)
    limiter.admit(0.0, 900)
    assert limiter.delay(30.0, 900) == pytest.approx(30.0)
    assert limiter.delay(61.0, 900) == 0.0


# "after the response arrives, record actual `prompt_tokens + completion_tokens`
#  from the API response in the TPM window"
def test_actual_usage_replaces_the_reservation():
    limiter = RateLimiter(tpm=1000)
    reservation = limiter.admit(0.0, 900)
    assert limiter.delay(0.0, 500) > 0

    limiter.settle(reservation, 100)  # the reply only used 100 tokens
    assert limiter.delay(0.0, 500) == 0.0


# "if both RPM and TPM are configured, a request may be sent only when both
#  budgets have capacity" - here the token budget is the binding one
def test_token_budget_binds_while_requests_have_room():
    limiter = RateLimiter(rpm=600, tpm=10000)
    for index in range(16):
        limiter.admit(0.0, 612)  # "a typical request consumes about 612 tokens"
    assert limiter.delay(0.0, 612) > 0


# "if both RPM and TPM are configured, a request may be sent only when both
#  budgets have capacity" - here the request budget is the binding one
def test_request_budget_binds_while_tokens_have_room():
    limiter = RateLimiter(rpm=2, tpm=100000)
    limiter.admit(0.0, 10)
    limiter.admit(0.0, 10)
    assert limiter.delay(0.0, 10) == pytest.approx(WINDOW)


# "a request may be sent only when both budgets have capacity" - and a request
# larger than the whole token budget still goes out once the window drains (T72)
def test_oversized_request_is_not_stuck_forever():
    limiter = RateLimiter(tpm=500)
    limiter.admit(0.0, 400)
    assert limiter.delay(0.0, 900) == pytest.approx(WINDOW)
    assert limiter.delay(61.0, 900) == 0.0


# "before sending a request, estimate prompt tokens by counting words in the
#  rendered messages using `1 token ~= 0.75 words`, rounded up"
@pytest.mark.parametrize("words,tokens", [(0, 0), (1, 2), (3, 4), (75, 100), (76, 102)])
def test_prompt_token_estimate_rounds_up(words, tokens):
    assert estimate_tokens(words) == tokens


# "counting words in the rendered messages" - every message of a chat request
def test_chat_payload_words_count_every_message():
    payload = {"messages": [
        {"role": "system", "content": "two words"},
        {"role": "user", "content": "three more words"},
    ]}
    assert payload_words(payload) == 5


# "counting words in the rendered messages" - a completions request carries the
# conversation as one rendered prompt string
def test_completions_payload_words_count_the_rendered_prompt():
    assert payload_words({"prompt": "one two three four"}) == 4


# "rows are still paired with outputs in input order even when requests overlap"
# - waiters are admitted in the order they arrived
def test_reserve_admits_waiters_in_arrival_order():
    async def scenario():
        limiter = RateLimiter(rpm=4)  # only four fit, so later waiters queue
        admitted = []

        async def waiter(index):
            await limiter.reserve(10)
            admitted.append(index)

        await asyncio.wait_for(
            asyncio.gather(*(waiter(index) for index in range(4))), timeout=5
        )
        return admitted

    assert asyncio.run(scenario()) == [0, 1, 2, 3]


# "`max_concurrent` is a hard cap on in-flight requests independent of RPM and TPM"
def test_concurrency_caps_simultaneous_holders():
    async def scenario():
        concurrency = Concurrency(2)
        seen = []
        live = 0

        async def holder():
            nonlocal live
            async with concurrency.hold():
                live += 1
                seen.append(live)
                await asyncio.sleep(0.01)
                live -= 1

        await asyncio.gather(*(holder() for _ in range(6)))
        return seen

    assert max(asyncio.run(scenario())) == 2


# "for agentic loops ... the loop holds one concurrency slot for its entire
#  lifetime" - requests inside a held slot do not take a second one
def test_concurrency_hold_is_reentrant_within_one_task():
    async def scenario():
        concurrency = Concurrency(1)
        async with concurrency.hold():
            async with concurrency.hold():  # would deadlock if it took a slot
                return True

    assert asyncio.run(asyncio.wait_for(scenario(), timeout=5))


# "`max_concurrent` is a hard cap ... independent of RPM and TPM" - no cap means
# no slot to wait for
def test_no_max_concurrent_means_no_cap():
    async def scenario():
        concurrency = Concurrency(None)
        async with concurrency.hold():
            async with concurrency.hold():
                return True

    assert asyncio.run(scenario())
