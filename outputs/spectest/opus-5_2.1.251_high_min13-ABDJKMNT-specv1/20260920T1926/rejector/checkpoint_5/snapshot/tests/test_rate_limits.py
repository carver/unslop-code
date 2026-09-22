"""Token-aware scheduling: sliding RPM/TPM windows and the concurrency cap."""

from __future__ import annotations

import asyncio
import time

from conftest import agentic_task, base_defaults, base_task, judge_task, math_task
from fake_api import FakeAPI, Reply, always, by_question, by_system, call, turns
from taskrunner.config import build_run_config
from taskrunner.limits import RateLimiter, SlidingWindow, estimate_prompt_tokens

WINDOW = 60.0


def build(task: dict, **overrides):
    """Build a single-task config, with CLI overrides applied."""
    return build_run_config({"task": task}, overrides).tasks["gsm8k_solve"]


# Spec: "defaults: rate_limits: {rpm: 100, tpm: 50000, max_concurrent: 10}" and
# "For multi-task configs, defaults.rate_limits is merged into each task the
# same way earlier checkpoints merged prompt, generation, and evaluation."
# Context: Rate Limits / Configuration.
def test_defaults_rate_limits_merge_into_every_task():
    document = {
        "defaults": {
            **base_defaults("http://localhost:8000"),
            "rate_limits": {"rpm": 100, "tpm": 50000, "max_concurrent": 10},
        },
        "tasks": {"a": math_task(), "b": math_task()},
    }
    config = build_run_config(document, {})
    for name in ("a", "b"):
        limits = config.tasks[name].limits
        assert (limits.rpm, limits.tpm, limits.max_concurrent) == (100, 50000, 10)


# Spec: "Per-task rate_limits keys override only the keys they specify."
# Context: Rate Limits / Per-task override.
def test_per_task_rate_limits_override_single_keys():
    document = {
        "defaults": {
            **base_defaults("http://localhost:8000"),
            "rate_limits": {"rpm": 100, "tpm": 50000, "max_concurrent": 10},
        },
        "tasks": {"code_gen": math_task(rate_limits={"tpm": 30000})},
    }
    limits = build_run_config(document, {}).tasks["code_gen"].limits
    assert (limits.rpm, limits.tpm, limits.max_concurrent) == (100, 30000, 10)


# Spec: "CLI flags: --tpm <int>".
# Context: Rate Limits / CLI flags.
def test_tpm_flag_overrides_config():
    task = base_task("http://localhost:8000", rate_limits={"tpm": 500})
    assert build(task, tpm=9000).limits.tpm == 9000


# Spec: "CLI flags: --max-concurrent <int>".
# Context: Rate Limits / CLI flags.
def test_max_concurrent_flag_overrides_config():
    task = base_task("http://localhost:8000", rate_limits={"max_concurrent": 3})
    assert build(task, max_concurrent=7).limits.max_concurrent == 7


# Spec: "--tpm <int>" / "--max-concurrent <int>" are accepted by the CLI.
# Context: Rate Limits / CLI flags.
def test_rate_limit_flags_are_accepted_end_to_end(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data, "--tpm", "10000", "--max-concurrent", "2")
    assert result.returncode == 0
    assert result.summary["total"] == 1


# Spec: "continue to enforce RPM, now using a sliding 60-second window".
# Context: Rate Limits / Rules; a window at its limit only frees room once the
# oldest request in it is 60 seconds old.
def test_rpm_window_frees_room_sixty_seconds_after_the_oldest_request():
    window = SlidingWindow(limit=2)
    window.spend(1, now=0.0)
    window.spend(1, now=10.0)
    assert window.delay(1, now=20.0) == 40.0
    assert window.delay(1, now=61.0) == 0.0


# Spec: "continue to enforce RPM, now using a sliding 60-second window" — the
# window slides rather than resetting on a fixed boundary.
# Context: Rate Limits / Rules.
def test_window_expires_entries_individually():
    window = SlidingWindow(limit=3)
    for moment in (0.0, 30.0, 45.0):
        window.spend(1, now=moment)
    assert window.used(now=61.0) == 2
    assert window.delay(1, now=61.0) == 0.0


# Spec: "if rpm is omitted, RPM limiting is disabled for that task".
# Context: Rate Limits / Rules.
def test_rpm_omitted_disables_rpm_limiting():
    task = base_task("http://localhost:8000")
    task.pop("rpm")
    config = build(task)
    assert config.limits.rpm is None
    assert RateLimiter(config.limits).requests is None


# Spec: "when tpm is configured, also enforce a sliding 60-second token budget".
# Context: Rate Limits / Rules.
def test_tpm_window_holds_a_token_budget():
    window = SlidingWindow(limit=1000)
    window.spend(700, now=0.0)
    assert window.delay(400, now=5.0) == 55.0
    assert window.delay(300, now=5.0) == 0.0


# Spec: "before sending a request, estimate prompt tokens by counting words in
# the rendered messages using 1 token ~= 0.75 words, rounded up".
# Context: Rate Limits / Rules.
def test_prompt_token_estimate_is_words_over_three_quarters():
    messages = [
        {"role": "system", "content": "one two three"},
        {"role": "user", "content": "four five six"},
    ]
    assert estimate_prompt_tokens(messages) == 8  # ceil(6 / 0.75)
    assert estimate_prompt_tokens([{"role": "user", "content": "a b c d"}]) == 6
    assert estimate_prompt_tokens([{"role": "user", "content": "solo"}]) == 2


# Spec: "reserve against estimated_prompt_tokens + max_tokens before dispatch".
# Context: Rate Limits / Rules.
def test_reservation_claims_the_estimate_before_dispatch():
    limits = build(base_task("http://localhost:8000", rate_limits={"tpm": 5000})).limits
    limiter = RateLimiter(limits)
    asyncio.run(limiter.reserve(612))
    assert limiter.tokens.used(time.monotonic()) == 612


# Spec: "after the response arrives, record actual prompt_tokens +
# completion_tokens from the API response in the TPM window".
# Context: Rate Limits / Rules; the reservation is replaced, not added to.
def test_settling_replaces_the_reservation_with_actual_usage():
    limits = build(base_task("http://localhost:8000", rate_limits={"tpm": 5000})).limits
    limiter = RateLimiter(limits)
    reservation = asyncio.run(limiter.reserve(612))
    reservation.settle(130)
    assert limiter.tokens.used(time.monotonic()) == 130


# Spec: "if both RPM and TPM are configured, a request may be sent only when
# both budgets have capacity".
# Context: Rate Limits / Rules.
def test_both_budgets_must_have_capacity():
    limits = build(
        base_task("http://localhost:8000", rate_limits={"rpm": 600, "tpm": 1000})
    ).limits
    limiter = RateLimiter(limits)
    asyncio.run(limiter.reserve(900))
    now = time.monotonic()
    assert limiter.requests.delay(1, now) == 0.0
    assert limiter.tokens.delay(900, now) > 0.0
    assert limiter.delay(900, now) > 0.0


# Spec: "max_concurrent is a hard cap on in-flight requests independent of RPM
# and TPM".
# Context: Rate Limits / Rules.
def test_max_concurrent_caps_in_flight_requests(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=8, delay=0.2) as api:
        task = base_task(api.url, rate_limits={"rpm": 600, "max_concurrent": 2})
        config = write_config(task)
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(10)])
        run_cli(config, data)
        assert api.max_concurrent == 2


# Spec: "rows are still paired with outputs in input order even when requests
# overlap; concurrent execution must not cause a later input row to consume the
# response intended for an earlier row".
# Context: Rate Limits / Rules.
def test_rows_keep_their_own_responses_under_the_cap(write_config, write_input, run_cli):
    rows = [{"question": f"q{i}", "answer": str(i)} for i in range(12)]
    mapping = {f"q{i}": Reply(content=f"#### {i}") for i in range(12)}
    with FakeAPI(responder=by_question(mapping), slots=8, delay=0.1) as api:
        task = base_task(api.url, rate_limits={"rpm": 600, "max_concurrent": 4})
        result = run_cli(write_config(task), write_input(rows))
    for index, row in enumerate(result.rows):
        assert row["input"]["question"] == f"q{index}"
        assert row["output"]["solution"] == f"#### {index}"


# Spec: "each llm_judge call goes through the same limiter".
# Context: Rate Limits / Rules; with one slot the judge cannot overlap the
# generation it scores.
def test_judge_calls_share_the_concurrency_cap(write_config, write_input, run_cli):
    replies = {
        "You are a writing assistant.": Reply(content="a draft"),
        "You are a quality evaluator.": Reply(content="9"),
    }
    with FakeAPI(responder=by_system(replies), slots=8, delay=0.1) as api:
        task = judge_task(
            name="gsm8k_solve",
            api_url=api.url,
            model="gpt-4",
            rate_limits={"rpm": 600, "max_concurrent": 1},
        )
        rows = [{"prompt_text": f"p{i}", "criteria": "clear"} for i in range(4)]
        run_cli(write_config(task), write_input(rows))
        assert api.max_concurrent == 1
        assert api.call_count == 8


# Spec: "for agentic loops, every API request counts toward RPM and TPM, and
# the loop holds one concurrency slot for its entire lifetime".
# Context: Rate Limits / Rules; one slot means two rows never interleave.
def test_agentic_loop_holds_one_slot_for_its_lifetime(write_config, write_input, run_cli):
    script = [
        Reply(content=None, tools=(call("lookup", key="employees"),)),
        Reply(content="#### 142"),
    ]
    rows = [{"question": f"q{i}", "answer": "142"} for i in range(3)]
    with FakeAPI(responder=turns(script), slots=8, delay=0.1) as api:
        task = agentic_task(api.url, rate_limits={"rpm": 600, "max_concurrent": 1})
        run_cli(write_config(task), write_input(rows))
        asked = [body["messages"][1]["content"] for body in api.requests]
        assert api.max_concurrent == 1
        assert api.call_count == 6
    # One slot per loop, so a row's two requests are adjacent rather than
    # interleaved with the other rows'.
    assert asked == ["q0", "q0", "q1", "q1", "q2", "q2"]
