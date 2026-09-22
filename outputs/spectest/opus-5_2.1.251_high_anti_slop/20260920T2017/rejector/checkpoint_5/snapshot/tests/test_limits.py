"""The sliding windows and the concurrency cap that pace requests."""

import asyncio
import time

import pytest

from config import RateLimits
from limits import (
    WINDOW_SECONDS,
    RequestLimiter,
    Reservation,
    SlidingWindow,
    estimate_prompt_tokens,
)

NOW = 1000.0
MESSAGES = [
    {"role": "system", "content": "Solve the problem"},
    {"role": "assistant", "content": None},
    {"role": "user", "content": "What is two plus two"},
]


def test_prompt_tokens_are_estimated_from_the_words_of_every_message():
    """Eight words at 0.75 words per token, rounded up; the empty turn adds none."""
    assert estimate_prompt_tokens(MESSAGES) == 11


def test_a_window_without_a_limit_never_waits():
    window = SlidingWindow(None)
    window.add(NOW, 10_000)
    assert window.delay(NOW, 10_000) == 0.0


def test_a_window_with_room_does_not_wait():
    window = SlidingWindow(100)
    window.add(NOW, 60)
    assert window.delay(NOW, 40) == 0.0


def test_a_full_window_waits_for_its_oldest_spend_to_age_out():
    window = SlidingWindow(100)
    window.add(NOW, 60)
    window.add(NOW + 10, 40)
    assert window.delay(NOW + 20, 1) == pytest.approx(WINDOW_SECONDS - 20)


def test_spends_older_than_the_window_stop_counting():
    window = SlidingWindow(100)
    window.add(NOW, 100)
    assert window.delay(NOW + WINDOW_SECONDS, 100) == 0.0


def test_an_empty_window_admits_a_request_larger_than_the_whole_limit():
    assert SlidingWindow(100).delay(NOW, 5_000) == 0.0


def test_recording_the_real_usage_frees_what_the_estimate_over_reserved():
    window = SlidingWindow(100)
    reservation = Reservation(window.add(NOW, 90))
    assert window.delay(NOW, 50) > 0

    reservation.record(20)
    assert window.delay(NOW, 50) == 0.0


async def test_a_request_is_admitted_once_both_budgets_have_room():
    limiter = RequestLimiter(RateLimits(rpm=2, tpm=1000))
    for _ in range(2):
        await limiter.reserve(400)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(limiter.reserve(400), timeout=0.2)


async def test_the_token_budget_binds_before_the_request_budget():
    """Room for 100 requests a minute, but only two of this size."""
    limiter = RequestLimiter(RateLimits(rpm=100, tpm=1000))
    await limiter.reserve(600)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(limiter.reserve(600), timeout=0.2)


async def test_max_concurrent_caps_the_work_in_flight():
    limiter = RequestLimiter(RateLimits(max_concurrent=2))
    in_flight = 0
    peak = 0

    async def unit():
        nonlocal in_flight, peak
        async with limiter.in_flight():
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1

    await asyncio.gather(*(unit() for _ in range(6)))
    assert peak == 2


async def test_work_is_unbounded_without_max_concurrent():
    limiter = RequestLimiter(RateLimits(rpm=100))
    async with limiter.in_flight():
        started = time.monotonic()
        async with limiter.in_flight():
            assert time.monotonic() - started < 0.1
