"""The sliding request and token windows, and the prompt estimate that feeds them."""

import asyncio
import time

import pytest

from limits import RateLimits, RequestLimiter, SlidingWindow, estimate_tokens


def test_a_window_without_a_limit_never_delays():
    window = SlidingWindow(None)
    window.add(1_000_000)
    assert window.delay_for(1_000_000) == 0.0


def test_a_window_with_room_admits_straight_away():
    window = SlidingWindow(10)
    window.add(6)
    assert window.delay_for(4) == 0.0


def test_a_window_waits_only_for_the_entries_it_needs():
    window = SlidingWindow(10)
    now = time.monotonic()
    window.add(6).at = now - 50  # leaves the window in 10s
    window.add(4).at = now - 20  # leaves the window in 40s

    assert window.delay_for(3) == pytest.approx(10, abs=0.5)
    assert window.delay_for(8) == pytest.approx(40, abs=0.5)


def test_settling_a_reservation_frees_the_room_it_did_not_use():
    window = SlidingWindow(100)
    reservation = window.add(90)
    assert window.delay_for(20) > 0

    reservation.settle(10)
    assert window.delay_for(20) == 0.0


def test_a_request_larger_than_the_whole_budget_still_goes_out():
    assert SlidingWindow(100).delay_for(500) == 0.0


def test_prompt_tokens_are_estimated_from_the_rendered_words():
    messages = [{"role": "system", "content": "one two three"}, {"role": "user", "content": "four five"}]
    assert estimate_tokens(messages) == 7  # five words at 0.75 words per token, rounded up


def test_turns_without_text_cost_nothing():
    assert estimate_tokens([{"role": "assistant", "content": None}]) == 0


def test_the_token_budget_holds_back_what_the_request_budget_would_allow():
    limiter = RequestLimiter(RateLimits(rpm=6000, tpm=1000))

    async def spend_the_token_budget():
        await limiter.reserve(600)
        await limiter.reserve(400)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(limiter.reserve(400), timeout=0.1)

    asyncio.run(spend_the_token_budget())


def test_without_a_token_budget_only_the_request_budget_applies():
    limiter = RequestLimiter(RateLimits(rpm=6000))

    async def spend():
        for _ in range(20):
            await limiter.reserve(100_000)

    asyncio.run(asyncio.wait_for(spend(), timeout=1.0))
