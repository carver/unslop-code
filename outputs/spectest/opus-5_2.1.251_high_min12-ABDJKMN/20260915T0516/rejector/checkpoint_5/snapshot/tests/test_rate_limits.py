"""Part 5: token-aware scheduling - rpm, tpm, and max_concurrent."""
import math
import time

import pytest

import rejector
from conftest import (judge_task, limits_block, make_config, make_multi_config,
                      agentic_config, static_map_tool)
from mock_api import MockAPI, agentic_turns, always, by_text, chat_response


# --------------------------------------------------------------- config ---

# Spec: "defaults:\n  rate_limits:\n    rpm: 100\n    tpm: 50000\n
#        max_concurrent: 10"
# Context: Rate Limits / Configuration. The block validates and is readable
# off the built task config.
def test_rate_limits_block_is_accepted(run_tool):
    limits = limits_block(rpm=100, tpm=50000, max_concurrent=10)
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, rate_limits=limits),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr


# Spec: "defaults.rate_limits is merged into each task the same way earlier
#        checkpoints merged prompt, generation, and evaluation"
# Context: Rate Limits / multi-task configs.
def test_defaults_rate_limits_merge_into_each_task():
    config = make_multi_config(
        defaults={"rate_limits": limits_block(rpm=100, tpm=50000,
                                              max_concurrent=10)})
    multi, specs = rejector.split_config(config)
    assert multi
    for _name, task in specs:
        assert task["rate_limits"] == {"rpm": 100, "tpm": 50000,
                                       "max_concurrent": 10}


# Spec: "Per-task `rate_limits` keys override only the keys they specify."
# Context: the per-task override example sets only `tpm`.
def test_per_task_rate_limits_override_only_named_keys():
    config = make_multi_config(
        defaults={"rate_limits": limits_block(rpm=100, tpm=50000,
                                              max_concurrent=10)},
        tasks={"code_gen": {"prompt": {"user": "{question}"},
                            "generation": {"scheme": "greedy"},
                            "rate_limits": {"tpm": 30000}}})
    _multi, specs = rejector.split_config(config)
    _name, task = specs[0]
    assert task["rate_limits"] == {"rpm": 100, "tpm": 30000,
                                   "max_concurrent": 10}


# Spec: the built task carries the merged limits.
def test_built_task_exposes_merged_limits(_args):
    config = make_multi_config(
        defaults={"rate_limits": limits_block(rpm=100, tpm=50000,
                                              max_concurrent=10)},
        tasks={"code_gen": {"prompt": {"user": "{question}"},
                            "generation": {"scheme": "greedy"},
                            "rate_limits": {"tpm": 30000}}})
    _multi, specs = rejector.split_config(config)
    built = rejector.build_task_config(specs[0][1], _args, "code_gen", True)
    assert built.rpm == 100
    assert built.tpm == 30000
    assert built.max_concurrent == 10


# Spec: "if `rpm` is omitted, RPM limiting is disabled for that task"
# Context: Rate Limits / Rules.
def test_rpm_omitted_disables_rpm_limiting(_args):
    task = {"api_url": "http://x", "model": "m",
            "prompt": {"user": "{question}"},
            "generation": {"scheme": "greedy"}}
    built = rejector.build_task_config(task, _args, "t")
    assert built.rpm is None


# Spec: "--tpm <int>"
# Context: Rate Limits / CLI flags.
def test_tpm_cli_flag_is_accepted(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}],
                       args=["--tpm", "50000"])
    assert run.returncode == 0, run.stderr


# Spec: "--max-concurrent <int>"
# Context: Rate Limits / CLI flags.
def test_max_concurrent_cli_flag_is_accepted(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}],
                       args=["--max-concurrent", "2"])
    assert run.returncode == 0, run.stderr


# Spec: CLI flags override the configured values.
def test_cli_flags_override_config_limits(_args):
    task = {"api_url": "http://x", "model": "m",
            "prompt": {"user": "{question}"},
            "generation": {"scheme": "greedy"},
            "rate_limits": {"rpm": 10, "tpm": 100, "max_concurrent": 1}}
    args = rejector.build_parser().parse_args(
        ["run", "--config", "c", "--output", "o", "--input", "i",
         "--rpm", "50", "--tpm", "999", "--max-concurrent", "7"])
    built = rejector.build_task_config(task, args, "t")
    assert (built.rpm, built.tpm, built.max_concurrent) == (50, 999, 7)


# ------------------------------------------------------ token estimates ---

# Spec: "estimate prompt tokens by counting words in the rendered messages
#        using `1 token ~= 0.75 words`, rounded up"
# Context: Rate Limits / Rules.
def test_prompt_token_estimate_rounds_up():
    messages = [{"role": "system", "content": "one two three"},
                {"role": "user", "content": "four five"}]
    # 5 words / 0.75 = 6.67 -> 7
    assert rejector.estimate_prompt_tokens(messages) == 7


def test_prompt_token_estimate_scales_with_word_count():
    messages = [{"role": "user", "content": " ".join("w" * 1 for _ in range(30))}]
    assert rejector.estimate_prompt_tokens(messages) == int(math.ceil(30 / 0.75))


# Spec: "reserve against `estimated_prompt_tokens + max_tokens` before
#        dispatch"
# Context: Rate Limits / Rules.
def test_reservation_is_estimate_plus_max_tokens():
    limiter = rejector.RateLimiter(tpm=10000)
    reserved = limiter.reserve(estimate=100, max_tokens=512, now=0.0)
    assert limiter.tokens_used(now=0.0) == 612
    assert reserved.amount == 612


# Spec: "after the response arrives, record actual `prompt_tokens +
#        completion_tokens` from the API response in the TPM window"
# Context: Rate Limits / Rules. The reservation is replaced by the actual.
def test_actual_tokens_replace_the_reservation():
    limiter = rejector.RateLimiter(tpm=10000)
    reserved = limiter.reserve(estimate=100, max_tokens=512, now=0.0)
    limiter.settle(reserved, 45 + 120)
    assert limiter.tokens_used(now=0.0) == 165


# ------------------------------------------------------ sliding windows ---

# Spec: "continue to enforce RPM, now using a sliding 60-second window"
# Context: Rate Limits / Rules.
def test_rpm_window_slides_over_60_seconds():
    limiter = rejector.RateLimiter(rpm=2)
    limiter.reserve(estimate=1, max_tokens=1, now=0.0)
    limiter.reserve(estimate=1, max_tokens=1, now=10.0)
    # The window is full until the first request is 60s old.
    assert limiter.delay(estimate=1, max_tokens=1, now=11.0) == pytest.approx(49.0)
    assert limiter.delay(estimate=1, max_tokens=1, now=60.0) == pytest.approx(0.0)
    # And once it slides, only the second request is still inside it.
    limiter.reserve(estimate=1, max_tokens=1, now=60.0)
    assert limiter.delay(estimate=1, max_tokens=1, now=60.0) == pytest.approx(10.0)


def test_rpm_disabled_when_not_configured():
    limiter = rejector.RateLimiter(rpm=None)
    for i in range(1000):
        assert limiter.delay(estimate=1, max_tokens=1, now=0.0) == 0.0
        limiter.reserve(estimate=1, max_tokens=1, now=0.0)


# Spec: "when `tpm` is configured, also enforce a sliding 60-second token
#        budget"
# Context: Rate Limits / Rules.
def test_tpm_window_slides_over_60_seconds():
    limiter = rejector.RateLimiter(tpm=1000)
    limiter.reserve(estimate=100, max_tokens=500, now=0.0)   # 600 tokens
    assert limiter.delay(estimate=100, max_tokens=500, now=1.0) > 0
    assert limiter.delay(estimate=100, max_tokens=500, now=60.0) == pytest.approx(0.0)


def test_tpm_disabled_when_not_configured():
    limiter = rejector.RateLimiter(rpm=1000)
    limiter.reserve(estimate=10 ** 6, max_tokens=10 ** 6, now=0.0)
    assert limiter.delay(estimate=10 ** 6, max_tokens=10 ** 6, now=0.0) == 0.0


# Spec: "if both RPM and TPM are configured, a request may be sent only when
#        both budgets have capacity"
# Context: Rate Limits / Rules.
def test_both_budgets_must_have_capacity():
    limiter = rejector.RateLimiter(rpm=10, tpm=1000)
    limiter.reserve(estimate=100, max_tokens=800, now=0.0)   # rpm fine, tpm full
    assert limiter.delay(estimate=100, max_tokens=800, now=1.0) > 0

    limiter = rejector.RateLimiter(rpm=1, tpm=10 ** 6)
    limiter.reserve(estimate=1, max_tokens=1, now=0.0)       # tpm fine, rpm full
    assert limiter.delay(estimate=1, max_tokens=1, now=1.0) > 0


# Spec: "TPM bottleneck: if `rpm: 600`, `tpm: 10000`, and a typical request
#        consumes about 612 tokens ... the scheduler should pace close to the
#        token budget instead of the higher request budget"
# Context: Rate Limits / Examples.
def test_tpm_is_the_binding_limit_when_it_is_tighter():
    limiter = rejector.RateLimiter(rpm=600, tpm=10000)
    sent = 0
    while limiter.delay(estimate=100, max_tokens=512, now=0.0) == 0.0:
        limiter.reserve(estimate=100, max_tokens=512, now=0.0)
        sent += 1
        assert sent < 600
    # 10000 / 612 = 16 requests per window, far below the 600 rpm budget.
    assert sent == 16


# ---------------------------------------------------------- end to end ---

# Spec: "`max_concurrent` is a hard cap on in-flight requests independent of
#        RPM and TPM"
# Context: Rate Limits / Rules.
def test_max_concurrent_caps_in_flight_requests(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(8)]
    with MockAPI(always("#### 5"), service_seconds=0.05) as api:
        run = run_tool(make_config(api_url=api.url, rpm=6000,
                                   rate_limits=limits_block(max_concurrent=2)),
                       rows)
    assert run.returncode == 0, run.stderr
    assert api.max_concurrent <= 2


def test_max_concurrent_one_serialises_requests(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(5)]
    with MockAPI(always("#### 5"), service_seconds=0.05) as api:
        run = run_tool(make_config(api_url=api.url, rpm=6000),
                       rows, args=["--max-concurrent", "1"])
    assert run.returncode == 0, run.stderr
    assert api.max_concurrent == 1
    assert len(run.rows) == 5


# Spec: "rows are still paired with outputs in input order even when requests
#        overlap; concurrent execution must not cause a later input row to
#        consume the response intended for an earlier row"
# Context: Rate Limits / Rules.
def test_rows_pair_with_their_own_outputs_under_concurrency(run_tool):
    rows = [{"question": "q%d" % i, "answer": str(i)} for i in range(12)]

    def responder(payload, index):
        user = [m for m in payload["messages"] if m["role"] == "user"][-1]
        number = user["content"].replace("q", "")
        # A jittered delay makes responses come back out of request order.
        time.sleep(0.02 * (index % 4))
        return 200, chat_response("#### %s" % number)

    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, rpm=6000), rows)
    assert run.returncode == 0, run.stderr
    assert api.max_concurrent > 1
    out = run.rows
    assert [r["input"]["question"] for r in out] == ["q%d" % i for i in range(12)]
    for i, record in enumerate(out):
        assert record["output"]["solution"] == "#### %d" % i
        assert record["result"]["passed"] is True


# Spec: "each `llm_judge` call goes through the same limiter"
# Context: Rate Limits / Rules. With max_concurrent 1 nothing overlaps, and
# the judge call is one of the requests being serialised.
def test_judge_calls_share_the_limiter(run_tool):
    rows = [{"prompt_text": "p%d" % i, "criteria": "good"} for i in range(4)]
    responder = by_text([("Rate this response", "9")], default="an answer")
    with MockAPI(responder, service_seconds=0.05) as api:
        run = run_tool({"task": dict(judge_task(),
                                     name="j", api_url=api.url, model="gpt-4",
                                     rpm=6000,
                                     rate_limits=limits_block(max_concurrent=1))},
                       rows)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 8
    assert api.max_concurrent == 1


# Spec: "for agentic loops, every API request counts toward RPM and TPM, and
#        the loop holds one concurrency slot for its entire lifetime"
# Context: Rate Limits / Rules.
def test_agentic_loop_holds_one_slot_and_still_completes(run_tool):
    rows = [{"question": "q%d" % i, "answer": "142"} for i in range(3)]
    steps = [[("lookup", {"key": "employees"})], "#### 142"]
    with MockAPI(agentic_turns(steps), service_seconds=0.02) as api:
        run = run_tool(agentic_config(api.url, tools=[static_map_tool()],
                                      rpm=6000,
                                      rate_limits=limits_block(max_concurrent=1)),
                       rows)
    assert run.returncode == 0, run.stderr
    assert api.max_concurrent == 1
    assert api.call_count == 6            # two requests per loop
    assert len(run.rows) == 3
    assert all(r["result"]["iterations"] == 2 for r in run.rows)


# Spec: "for agentic loops, every API request counts toward RPM and TPM"
# Context: a two-iteration loop consumes two slots of the rpm window.
def test_every_agentic_request_counts_toward_rpm(run_tool):
    rows = [{"question": "q", "answer": "142"}]
    steps = [[("lookup", {"key": "employees"})], "#### 142"]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url, tools=[static_map_tool()],
                                      rpm=6000), rows)
    assert run.returncode == 0, run.stderr
    assert run.summary["total_api_calls"] == 2


# Spec: "continue to enforce RPM, now using a sliding 60-second window"
# Context: end to end - a low rpm paces dispatch; the burst is capped at rpm
# requests per window. The run is stopped once the burst has been observed.
def test_rpm_burst_is_capped_end_to_end(run_bg):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(20)]
    with MockAPI(always("#### 5")) as api:
        proc = run_bg(make_config(api_url=api.url,
                                  rate_limits=limits_block(rpm=5)), rows)
        time.sleep(3.0)
        seen = api.call_count
        proc.kill()
        proc.wait(timeout=10)
    assert seen == 5


# Spec: "when `tpm` is configured, also enforce a sliding 60-second token
#        budget" / the TPM bottleneck example.
# Context: 30 rows, tpm room for only a handful of ~612-token requests.
def test_tpm_paces_dispatch_end_to_end(run_bg):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(30)]
    limits = limits_block(rpm=6000, tpm=2000)
    with MockAPI(always("#### 5", prompt_tokens=45, completion_tokens=120)) as api:
        proc = run_bg(make_config(api_url=api.url, max_tokens=512,
                                  rate_limits=limits), rows)
        time.sleep(3.0)
        seen = api.call_count
        proc.kill()
        proc.wait(timeout=10)
    # Reservations of ~518 tokens each: at most 3 fit in a 2000-token window
    # up front. Actuals (165) are smaller, so a few more may follow.
    assert 3 <= seen <= 12
    assert seen < 30


@pytest.fixture
def _args():
    class Args(object):
        pass
    args = Args()
    for key in ("api_url", "model", "rpm", "tpm", "max_concurrent", "budget",
                "scheme", "temperature", "max_tokens", "n", "eval_model",
                "num_solutions", "api_type", "chat_template", "icl_strategy",
                "icl_k"):
        setattr(args, key, None)
    return args
