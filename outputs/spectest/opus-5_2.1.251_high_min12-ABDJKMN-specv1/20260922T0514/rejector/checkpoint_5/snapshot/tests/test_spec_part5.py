"""Tests derived phrase-by-phrase from the Part 5 (checkpoint 5) spec.

Part 5 adds token-aware scheduling (`rate_limits`), cost accounting with a
budget, `output_schema` validation, `--resume`, `--dry-run` and `--progress`.

Each section comment quotes the spec phrase under test plus the minimal
context needed to read it.
"""
import copy
import json
import re
import subprocess
import sys
import time

import pytest
import yaml

from conftest import (REJECTOR, CliResult, completion, make_config,
                      make_multi_config, tool_call_completion)

ROW = {"question": "What is 2 + 3?", "answer": "5"}
PASS = "2 + 3 = 5\n#### 5"


def rows(n, answer="5"):
    return [{"question": "q%d" % k, "answer": answer} for k in range(n)]


def limited(url, *, rate_limits=None, cost=None, rpm=60, **over):
    """The canonical greedy config plus Part 5 blocks."""
    cfg = make_config(url, rpm=rpm, **over)
    if rate_limits is not None:
        cfg["task"]["rate_limits"] = rate_limits
    if cost is not None:
        cfg["task"]["cost"] = cost
    return cfg


def usage_api(api, text=PASS, *, prompt_tokens=30, completion_tokens=10, delay=0.0):
    return api(lambda b, i: (200, completion(text, prompt_tokens=prompt_tokens,
                                             completion_tokens=completion_tokens)),
               delay=delay)


def wait_until(predicate, timeout=10.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ===========================================================================
# Rate Limits — configuration
# ===========================================================================

# "For multi-task configs, `defaults.rate_limits` is merged into each task the
#  same way earlier checkpoints merged `prompt`, `generation`, and
#  `evaluation`."
def test_defaults_rate_limits_merge_into_each_task(run_multi, api):
    mock = usage_api(api, delay=0.3)
    task = {"prompt": {"user": "{question}"}, "output_field": "solution",
            "generation": {"scheme": "greedy", "max_tokens": 16}}
    cfg = make_multi_config(mock.url, {"a": copy.deepcopy(task)},
                            defaults={"rate_limits": {"max_concurrent": 2}})
    r = run_multi(cfg, {"a": rows(8)})
    assert r.code == 0, r.stderr
    assert mock.max_inflight <= 2, mock.max_inflight


# "Per-task `rate_limits` keys override only the keys they specify."
def test_per_task_rate_limits_override_only_named_keys(run_multi, api):
    mock = usage_api(api, delay=0.3)
    task = {"prompt": {"user": "{question}"}, "output_field": "solution",
            "generation": {"scheme": "greedy", "max_tokens": 16},
            "rate_limits": {"tpm": 30000}}
    cfg = make_multi_config(mock.url, {"a": task},
                            defaults={"rate_limits": {"rpm": 1000,
                                                      "max_concurrent": 2}})
    r = run_multi(cfg, {"a": rows(8)})
    assert r.code == 0, r.stderr
    # tpm was overridden; max_concurrent from defaults survives untouched.
    assert mock.max_inflight <= 2, mock.max_inflight


# "CLI flags: --tpm <int>"
def test_tpm_flag_is_accepted(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [ROW], args=["--tpm", "50000"])
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == {"solution": "2 + 3 = 5\n#### 5"}


# "CLI flags: --max-concurrent <int>"
def test_max_concurrent_flag_is_accepted(run_cli, api):
    mock = usage_api(api, delay=0.25)
    r = run_cli(make_config(mock.url), rows(6), args=["--max-concurrent", "2"])
    assert r.code == 0, r.stderr
    assert mock.max_inflight <= 2, mock.max_inflight


def test_cli_rate_limit_flags_override_config(run_cli, api):
    mock = usage_api(api, delay=0.25)
    cfg = limited(mock.url, rate_limits={"max_concurrent": 8})
    r = run_cli(cfg, rows(6), args=["--max-concurrent", "1"])
    assert r.code == 0, r.stderr
    assert mock.max_inflight == 1


# ===========================================================================
# Rate Limits — RPM
# ===========================================================================

# "continue to enforce RPM, now using a sliding 60-second window"
def test_rpm_sliding_window_caps_the_first_minute(run_cli_bg, api):
    mock = usage_api(api)
    cfg = limited(mock.url, rate_limits={"rpm": 3})
    run = run_cli_bg(cfg, rows(8))
    assert wait_until(lambda: mock.call_count >= 3, timeout=15)
    time.sleep(1.5)
    # The window holds 3 requests for a full 60s, so nothing else goes out.
    assert mock.call_count == 3, mock.call_count
    assert run.proc.poll() is None, "run finished despite the rpm window"


# "continue to enforce RPM, now using a sliding 60-second window"
# The window is a burst budget, not an even pacing: under the cap, requests
# are not delayed at all.
def test_requests_under_the_rpm_cap_are_not_paced(run_cli, api):
    mock = usage_api(api, delay=0.2)
    cfg = limited(mock.url, rate_limits={"rpm": 100})
    start = time.time()
    r = run_cli(cfg, rows(20))
    elapsed = time.time() - start
    assert r.code == 0, r.stderr
    assert len(r.rows) == 20
    assert elapsed < 10, "20 requests under a 100 rpm cap took %.1fs" % elapsed


# "if `rpm` is omitted, RPM limiting is disabled for that task"
def test_rpm_omitted_disables_rpm_limiting(run_cli, api):
    mock = usage_api(api, delay=0.05)
    cfg = make_config(mock.url, rpm=None)
    # 70 rows is past the Part 1 default of 60: with no rpm configured there
    # is no window at all, so none of them may be held back for a minute.
    start = time.time()
    r = run_cli(cfg, rows(70))
    elapsed = time.time() - start
    assert r.code == 0, r.stderr
    assert len(r.rows) == 70
    assert mock.max_inflight > 1
    assert elapsed < 30, "no rpm configured but the run was throttled"


# "if `rpm` is omitted, RPM limiting is disabled for that task"
# With no rpm there is also no rate to divide by in the time estimate.
def test_dry_run_time_estimate_is_null_without_rpm(run_cli, api):
    mock = usage_api(api)
    r = run_cli(make_config(mock.url, rpm=None), rows(4), args=["--dry-run"])
    assert r.code == 0, r.stderr
    assert r.summary["est_time_minutes"] is None


# "if `rpm` is omitted, RPM limiting is disabled for that task" — but a
# task-level `rpm` from earlier checkpoints still configures it.
def test_legacy_task_level_rpm_still_limits(run_cli_bg, api):
    mock = usage_api(api)
    cfg = make_config(mock.url, rpm=2)
    run_cli_bg(cfg, rows(6))
    assert wait_until(lambda: mock.call_count >= 2, timeout=15)
    time.sleep(1.2)
    assert mock.call_count == 2, mock.call_count


# "if `rpm` is omitted, RPM limiting is disabled for that task"
# `rate_limits.rpm` wins over the task-level key.
def test_rate_limits_rpm_overrides_task_level_rpm(run_cli, api):
    mock = usage_api(api, delay=0.1)
    cfg = limited(mock.url, rpm=2, rate_limits={"rpm": 500})
    start = time.time()
    r = run_cli(cfg, rows(10))
    assert r.code == 0, r.stderr
    assert time.time() - start < 20


# ===========================================================================
# Rate Limits — TPM
# ===========================================================================

# "when `tpm` is configured, also enforce a sliding 60-second token budget"
# "reserve against `estimated_prompt_tokens + max_tokens` before dispatch"
def test_tpm_window_blocks_once_the_budget_is_spent(run_cli_bg, api):
    mock = usage_api(api, prompt_tokens=8, completion_tokens=8)
    cfg = limited(mock.url, rate_limits={"tpm": 20},
                  generation={"scheme": "greedy", "max_tokens": 5},
                  prompt={"user": "{question}"})
    # "q0" renders to 1 word -> ceil(1 / 0.75) = 2 estimated prompt tokens,
    # so each reservation is 2 + 5 = 7 and three fit in a 20-token window;
    # the settled actuals (8 + 8 = 16 each) then block everything else.
    run = run_cli_bg(cfg, rows(8))
    assert wait_until(lambda: mock.call_count >= 1, timeout=15)
    time.sleep(1.5)
    assert 1 <= mock.call_count <= 3, mock.call_count
    assert run.proc.poll() is None, "run finished despite the tpm window"


# "before sending a request, estimate prompt tokens by counting words in the
#  rendered messages using `1 token ~= 0.75 words`, rounded up"
# 9 rendered words -> ceil(9 / 0.75) = 12 tokens (not 9 * 0.75 = 7).
def test_prompt_token_estimate_divides_by_0_75(run_cli_bg, api):
    mock = usage_api(api, prompt_tokens=0, completion_tokens=0, delay=4.0)
    nine_words = "one two three four five six seven eight {question}"
    cfg = limited(mock.url, rate_limits={"tpm": 39},
                  generation={"scheme": "greedy", "max_tokens": 8},
                  prompt={"user": nine_words})
    # Reservation per request is 12 + 8 = 20, so only one fits in 39 tokens.
    # Under the other reading it would be 7 + 8 = 15 and two would fit.
    run_cli_bg(cfg, rows(4))
    assert wait_until(lambda: mock.call_count >= 1, timeout=15)
    time.sleep(1.5)
    assert mock.call_count == 1, mock.call_count


# "after the response arrives, record actual `prompt_tokens +
#  completion_tokens` from the API response in the TPM window"
# The actuals are tiny here, so the window drains and the whole run finishes
# even though the up-front reservations are much larger.
def test_actual_usage_replaces_the_reservation(run_cli, api):
    mock = usage_api(api, prompt_tokens=1, completion_tokens=1)
    cfg = limited(mock.url, rate_limits={"tpm": 60},
                  generation={"scheme": "greedy", "max_tokens": 20},
                  prompt={"user": "{question}"})
    start = time.time()
    r = run_cli(cfg, rows(10))
    elapsed = time.time() - start
    assert r.code == 0, r.stderr
    assert len(r.rows) == 10
    # 10 reservations of 22 would be 220 tokens; settling to 2 each keeps the
    # 60-token window well clear, so the run must not stall for a minute.
    assert elapsed < 30, "TPM window did not settle to actual usage: %.1fs" % elapsed


# "if both RPM and TPM are configured, a request may be sent only when both
#  budgets have capacity"
def test_rpm_binds_even_when_tpm_is_generous(run_cli_bg, api):
    mock = usage_api(api, prompt_tokens=1, completion_tokens=1)
    cfg = limited(mock.url, rate_limits={"rpm": 2, "tpm": 10 ** 9})
    run_cli_bg(cfg, rows(8))
    assert wait_until(lambda: mock.call_count >= 2, timeout=15)
    time.sleep(1.2)
    assert mock.call_count == 2, mock.call_count


# "if both RPM and TPM are configured, a request may be sent only when both
#  budgets have capacity"
def test_tpm_binds_even_when_rpm_is_generous(run_cli_bg, api):
    mock = usage_api(api, prompt_tokens=500, completion_tokens=500)
    cfg = limited(mock.url, rate_limits={"rpm": 10000, "tpm": 1200},
                  generation={"scheme": "greedy", "max_tokens": 100},
                  prompt={"user": "{question}"})
    # Each reservation is ceil(1 / 0.75) + 100 = 102 tokens, so at most 11 of
    # the 20 rows fit in the 1200-token window; rpm would have allowed all 20.
    run = run_cli_bg(cfg, rows(20))
    assert wait_until(lambda: mock.call_count >= 1, timeout=15)
    time.sleep(1.5)
    assert mock.call_count <= 11, mock.call_count
    assert run.proc.poll() is None, "the tpm window did not bind"


# "if `rpm: 600`, `tpm: 10000`, and a typical request consumes about 612
#  tokens ... TPM, not RPM, becomes the binding limit ... the scheduler should
#  pace close to the token budget instead of the higher request budget"
def test_spec_example_tpm_is_the_binding_limit(run_cli_bg, api):
    mock = usage_api(api, prompt_tokens=100, completion_tokens=512)
    seventy_five_words = " ".join(["word"] * 74) + " {question}"
    cfg = limited(mock.url, rate_limits={"rpm": 600, "tpm": 10000},
                  generation={"scheme": "greedy", "max_tokens": 512},
                  prompt={"user": seventy_five_words})
    # ceil(75 / 0.75) + 512 = 612 tokens per request, so 16 fit in the 10000
    # token window while rpm alone would have let all 40 rows go at once.
    run_cli_bg(cfg, rows(40))
    assert wait_until(lambda: mock.call_count >= 1, timeout=15)
    time.sleep(2.0)
    assert mock.call_count <= 16, mock.call_count
    assert mock.call_count < 40, "rpm, not tpm, ended up binding"


# ===========================================================================
# Rate Limits — concurrency
# ===========================================================================

# "`max_concurrent` is a hard cap on in-flight requests independent of RPM and
#  TPM"
def test_max_concurrent_caps_in_flight_requests(run_cli, api):
    mock = usage_api(api, delay=0.3)
    cfg = limited(mock.url, rate_limits={"rpm": 10000, "tpm": 10 ** 9,
                                         "max_concurrent": 3})
    r = run_cli(cfg, rows(15))
    assert r.code == 0, r.stderr
    assert mock.max_inflight <= 3, mock.max_inflight
    assert mock.max_inflight >= 2, "cap of 3 never allowed real concurrency"


def test_max_concurrent_one_serializes_requests(run_cli, api):
    mock = usage_api(api, delay=0.05)
    cfg = limited(mock.url, rate_limits={"max_concurrent": 1})
    r = run_cli(cfg, rows(6))
    assert r.code == 0, r.stderr
    assert mock.max_inflight == 1


# "rows are still paired with outputs in input order even when requests
#  overlap; concurrent execution must not cause a later input row to consume
#  the response intended for an earlier row"
def test_rows_stay_paired_with_outputs_under_concurrency(run_cli, api):
    def responder(body, i):
        question = body["messages"][-1]["content"]
        # Slow the early rows down so later ones would finish first.
        index = int(question[1:])
        time.sleep(0.4 if index < 4 else 0.01)
        return 200, completion("answer for %s\n#### %d" % (question, index))

    mock = api(responder)
    cfg = limited(mock.url, rate_limits={"max_concurrent": 8},
                  prompt={"user": "{question}"}, evaluation=None)
    data = rows(10)
    r = run_cli(cfg, data)
    assert r.code == 0, r.stderr
    assert len(r.rows) == 10
    for index, row in enumerate(r.rows):
        assert row["input"] == data[index]
        assert row["output"]["solution"] == "answer for q%d\n#### %d" % (index, index)


# "each `llm_judge` call goes through the same limiter"
def test_judge_calls_go_through_the_limiter(run_cli, api):
    def responder(body, i):
        time.sleep(0.2)
        system = (body.get("messages") or [{}])[0].get("content", "")
        return 200, completion("8" if "evaluator" in system else "an answer")

    mock = api(responder)
    cfg = limited(mock.url, rate_limits={"max_concurrent": 2},
                  evaluation={"type": "llm_judge", "threshold": 7,
                              "judge_prompt": {
                                  "system": "You are an evaluator. Score 0-10.",
                                  "user": "Rate: {__response__}"}})
    r = run_cli(cfg, rows(6))
    assert r.code == 0, r.stderr
    assert mock.call_count == 12
    assert mock.max_inflight <= 2, mock.max_inflight


# ===========================================================================
# Rate Limits — agentic loops
# ===========================================================================

AGENT_TOOLS = [{
    "name": "lookup",
    "description": "Look up a value",
    "parameters": {"type": "object",
                   "properties": {"key": {"type": "string"}},
                   "required": ["key"]},
    "handler": {"type": "static_map", "mapping": {"x": "1"}, "default": "NONE"},
}]


def agentic_cfg(url, **over):
    cfg = {"task": {"name": "agent", "api_url": url, "model": "gpt-4",
                    "prompt": {"user": "{question}"},
                    "generation": {"scheme": "agentic", "max_iterations": 4,
                                   "temperature": 0.0, "max_tokens": 16},
                    "output_field": "answer",
                    "tools": copy.deepcopy(AGENT_TOOLS)}}
    for key, value in over.items():
        if value is None:
            cfg["task"].pop(key, None)
        else:
            cfg["task"][key] = value
    return cfg


def two_step_agentic(api, delay=0.0):
    """Every loop: one tool call, then a final answer."""
    state = {}

    def responder(body, i):
        question = body["messages"][0]["content"]
        seen = state.get(question, 0)
        state[question] = seen + 1
        if delay:
            time.sleep(delay)
        if seen == 0:
            return 200, tool_call_completion([{"name": "lookup",
                                               "arguments": {"key": "x"}}])
        return 200, completion("final for %s" % question)

    return api(responder)


# "for agentic loops, every API request counts toward RPM and TPM"
def test_every_agentic_request_counts_toward_rpm(run_cli_bg, api):
    mock = two_step_agentic(api)
    cfg = agentic_cfg(mock.url, rate_limits={"rpm": 3})
    run_cli_bg(cfg, rows(4))
    assert wait_until(lambda: mock.call_count >= 3, timeout=15)
    time.sleep(1.2)
    assert mock.call_count == 3, mock.call_count


# "the loop holds one concurrency slot for its entire lifetime"
def test_agentic_loop_holds_its_slot_for_the_whole_loop(run_cli, api):
    mock = two_step_agentic(api, delay=0.1)
    cfg = agentic_cfg(mock.url, rate_limits={"max_concurrent": 1})
    r = run_cli(cfg, rows(3))
    assert r.code == 0, r.stderr
    # With one slot held per loop, the two requests of each row are adjacent.
    questions = [b["messages"][0]["content"] for b in mock.bodies]
    assert len(questions) == 6
    for pair in range(3):
        assert questions[2 * pair] == questions[2 * pair + 1], questions


def test_agentic_loops_run_concurrently_up_to_max_concurrent(run_cli, api):
    mock = two_step_agentic(api, delay=0.3)
    cfg = agentic_cfg(mock.url, rate_limits={"max_concurrent": 3})
    r = run_cli(cfg, rows(6))
    assert r.code == 0, r.stderr
    assert mock.max_inflight <= 3, mock.max_inflight
    assert mock.max_inflight >= 2


# ===========================================================================
# Cost Tracking — configuration
# ===========================================================================

COST = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}


# "For multi-task configs, `defaults.cost` is merged into each task the same
#  way earlier checkpoints merged `prompt`, `generation`, and `evaluation`."
def test_defaults_cost_merges_into_each_task(run_multi, api):
    mock = usage_api(api, prompt_tokens=1000, completion_tokens=1000)
    task = {"prompt": {"user": "{question}"}, "output_field": "solution",
            "generation": {"scheme": "greedy", "max_tokens": 16}}
    cfg = make_multi_config(mock.url, {"a": copy.deepcopy(task)},
                            defaults={"cost": dict(COST)})
    r = run_multi(cfg, {"a": rows(1)})
    assert r.code == 0, r.stderr
    assert r.summary["cost"]["prompt"] == pytest.approx(0.01)
    assert r.summary["cost"]["completion"] == pytest.approx(0.03)
    assert r.summary["cost"]["total"] == pytest.approx(0.04)


# "Per-task `cost` keys override only the keys they specify."
def test_per_task_cost_overrides_only_named_keys(run_multi, api):
    mock = usage_api(api, prompt_tokens=1000, completion_tokens=1000)
    task = {"prompt": {"user": "{question}"}, "output_field": "solution",
            "generation": {"scheme": "greedy", "max_tokens": 16},
            "cost": {"prompt_cost_per_1k": 0.005}}
    cfg = make_multi_config(mock.url, {"a": task},
                            defaults={"cost": dict(COST, budget=50.0)})
    r = run_multi(cfg, {"a": rows(1)})
    assert r.code == 0, r.stderr
    # prompt rate overridden, completion rate and budget inherited.
    assert r.summary["cost"]["prompt"] == pytest.approx(0.005)
    assert r.summary["cost"]["completion"] == pytest.approx(0.03)
    assert r.summary["cost"]["budget"] == 50.0


# "CLI flag: --budget <float>"
def test_budget_flag_is_accepted(run_cli, api):
    mock = usage_api(api, prompt_tokens=10, completion_tokens=10)
    r = run_cli(limited(mock.url, cost=dict(COST)), [ROW],
                args=["--budget", "12.5"])
    assert r.code == 0, r.stderr
    assert r.summary["cost"]["budget"] == 12.5


# ===========================================================================
# Cost Tracking — accounting
# ===========================================================================

# "(prompt_tokens / 1000 * prompt_cost_per_1k) +
#  (completion_tokens / 1000 * completion_cost_per_1k)"
def test_cost_per_api_call_formula(run_cli, api):
    mock = usage_api(api, prompt_tokens=2500, completion_tokens=400)
    r = run_cli(limited(mock.url, cost=dict(COST)), [ROW])
    assert r.code == 0, r.stderr
    cost = r.summary["cost"]
    assert cost["prompt"] == pytest.approx(2500 / 1000 * 0.01)
    assert cost["completion"] == pytest.approx(400 / 1000 * 0.03)
    assert cost["total"] == pytest.approx(0.025 + 0.012)


# "track prompt cost, completion cost, and total cost across all tasks"
def test_cost_is_tracked_across_all_tasks(run_multi, api):
    mock = usage_api(api, prompt_tokens=1000, completion_tokens=1000)
    task = {"prompt": {"user": "{question}"}, "output_field": "solution",
            "generation": {"scheme": "greedy", "max_tokens": 16}}
    cfg = make_multi_config(mock.url,
                            {"a": copy.deepcopy(task), "b": copy.deepcopy(task)},
                            defaults={"cost": dict(COST)})
    r = run_multi(cfg, {"a": rows(2), "b": rows(3)})
    assert r.code == 0, r.stderr
    assert r.summary["cost"]["total"] == pytest.approx(5 * 0.04)


# "report them to at least four decimal places"
def test_cost_reported_to_at_least_four_decimals(run_cli, api):
    mock = usage_api(api, prompt_tokens=30, completion_tokens=10)
    r = run_cli(limited(mock.url, cost=dict(COST)), [ROW])
    assert r.code == 0, r.stderr
    cost = r.summary["cost"]
    # 30/1000*0.01 = 0.0003 and 10/1000*0.03 = 0.0003: a two-decimal report
    # would collapse both to 0.0.
    assert cost["prompt"] == pytest.approx(0.0003)
    assert cost["completion"] == pytest.approx(0.0003)
    assert cost["total"] == pytest.approx(0.0006)


# "include judge calls and every agentic iteration"
def test_cost_includes_judge_calls(run_cli, api):
    def responder(body, i):
        system = (body.get("messages") or [{}])[0].get("content", "")
        return 200, completion("8" if "evaluator" in system else "an answer",
                               prompt_tokens=1000, completion_tokens=1000)

    mock = api(responder)
    cfg = limited(mock.url, cost=dict(COST),
                  evaluation={"type": "llm_judge", "threshold": 7,
                              "judge_prompt": {
                                  "system": "You are an evaluator. Score 0-10.",
                                  "user": "Rate: {__response__}"}})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert mock.call_count == 2
    assert r.summary["cost"]["total"] == pytest.approx(2 * 0.04)


# "include judge calls and every agentic iteration"
def test_cost_includes_every_agentic_iteration(run_cli, api):
    state = {}

    def responder(body, i):
        question = body["messages"][0]["content"]
        seen = state.get(question, 0)
        state[question] = seen + 1
        if seen == 0:
            return 200, tool_call_completion(
                [{"name": "lookup", "arguments": {"key": "x"}}],
                prompt_tokens=1000, completion_tokens=1000)
        return 200, completion("final", prompt_tokens=1000, completion_tokens=1000)

    mock = api(responder)
    cfg = agentic_cfg(mock.url, cost=dict(COST))
    r = run_cli(cfg, rows(1))
    assert r.code == 0, r.stderr
    assert mock.call_count == 2
    assert r.summary["cost"]["total"] == pytest.approx(2 * 0.04)


# "if no cost configuration is present, omit the `cost` field from the summary"
def test_cost_field_omitted_without_cost_config(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [ROW])
    assert r.code == 0, r.stderr
    assert "cost" not in r.summary


def test_cost_field_present_with_cost_config(run_cli, api):
    mock = usage_api(api)
    r = run_cli(limited(mock.url, cost=dict(COST)), [ROW])
    assert r.code == 0, r.stderr
    assert "cost" in r.summary


# Summary shape:
# {"cost": {"total", "prompt", "completion", "budget", "budget_remaining",
#           "budget_exceeded"}}
def test_cost_summary_shape(run_cli, api):
    mock = usage_api(api, prompt_tokens=1000, completion_tokens=1000)
    r = run_cli(limited(mock.url, cost=dict(COST, budget=50.0)), [ROW])
    assert r.code == 0, r.stderr
    cost = r.summary["cost"]
    assert set(cost) == {"total", "prompt", "completion", "budget",
                         "budget_remaining", "budget_exceeded"}
    assert cost["budget"] == 50.0
    assert cost["budget_remaining"] == pytest.approx(50.0 - 0.04)
    assert cost["budget_exceeded"] is False


# T96: rates configured but no budget -> the budget keys are still present.
def test_cost_summary_without_budget_keeps_null_budget(run_cli, api):
    mock = usage_api(api)
    r = run_cli(limited(mock.url, cost=dict(COST)), [ROW])
    assert r.code == 0, r.stderr
    cost = r.summary["cost"]
    assert cost["budget"] is None
    assert cost["budget_remaining"] is None
    assert cost["budget_exceeded"] is False


# ===========================================================================
# Cost Tracking — budget exhaustion
# ===========================================================================

# "when `budget` is configured and the running total reaches or exceeds it:
#  stop sending new requests immediately, let in-flight requests finish, write
#  completed results, print the summary, and exit `0`"
def budget_cfg(url, budget):
    return limited(url, rate_limits={"max_concurrent": 1},
                   cost={"prompt_cost_per_1k": 0.01,
                         "completion_cost_per_1k": 0.0,
                         "budget": budget})


def test_budget_exhaustion_stops_new_requests(run_cli, api):
    # Each call costs 60000/1000 * 0.01 = $0.60; one slot keeps it serialized.
    mock = usage_api(api, prompt_tokens=60000, completion_tokens=0)
    r = run_cli(budget_cfg(mock.url, 1.00), rows(6))
    assert r.code == 0, r.stderr
    assert mock.call_count == 2, mock.call_count
    assert r.summary["cost"]["budget_exceeded"] is True


def test_budget_exhaustion_exits_zero_with_partial_output(run_cli, api):
    mock = usage_api(api, prompt_tokens=60000, completion_tokens=0)
    r = run_cli(budget_cfg(mock.url, 1.00), rows(6))
    assert r.code == 0, r.stderr
    assert len(r.rows) == 2, r.rows
    assert r.summary["total"] == 2


# "budget exhaustion is not an error; partial output is valid"
def test_budget_exhaustion_writes_nothing_on_stderr_as_an_error(run_cli, api):
    mock = usage_api(api, prompt_tokens=60000, completion_tokens=0)
    r = run_cli(budget_cfg(mock.url, 1.00), rows(6))
    assert r.code == 0
    assert "error:" not in r.stderr


# "if `budget: 1.00` and the running total reaches `$1.02` ... print
#  `cost.budget_exceeded: true`, exit 0"
def test_budget_exceeded_reports_overshoot(run_cli, api):
    # 51000 tokens * 0.01/1k = $0.51 per call; two calls reach $1.02.
    mock = usage_api(api, prompt_tokens=51000, completion_tokens=0)
    r = run_cli(budget_cfg(mock.url, 1.00), rows(5))
    assert r.code == 0, r.stderr
    cost = r.summary["cost"]
    assert cost["total"] == pytest.approx(1.02)
    assert cost["budget_exceeded"] is True
    assert cost["budget_remaining"] == pytest.approx(-0.02)


def test_budget_not_exceeded_when_total_stays_below(run_cli, api):
    mock = usage_api(api, prompt_tokens=1000, completion_tokens=0)
    r = run_cli(budget_cfg(mock.url, 50.0), rows(3))
    assert r.code == 0, r.stderr
    assert r.summary["cost"]["budget_exceeded"] is False
    assert len(r.rows) == 3


# ===========================================================================
# Structured Output Validation
# ===========================================================================

CODE_SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {"code": {"type": "string"},
                   "explanation": {"type": "string"}},
}

GOOD_JSON = json.dumps({"code": "def add(a, b): return a + b",
                        "explanation": "Simple addition function"})


def schema_cfg(url, schema=None, **over):
    cfg = make_config(url, rpm=None, evaluation=None, output_field="code")
    cfg["task"]["output_schema"] = copy.deepcopy(
        CODE_SCHEMA if schema is None else schema)
    for key, value in over.items():
        if value is None:
            cfg["task"].pop(key, None)
        else:
            cfg["task"][key] = value
    return cfg


# "on schema success, store the parsed JSON value in the per-row `output`
#  field instead of the raw response string"
def test_schema_success_stores_the_parsed_value(run_cli, api):
    mock = api(lambda b, i: (200, completion(GOOD_JSON)))
    r = run_cli(schema_cfg(mock.url), [ROW])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] == {"code": {"code": "def add(a, b): return a + b",
                                      "explanation": "Simple addition function"}}
    assert row["result"]["passed"] is True
    assert row["result"]["schema_valid"] is True


# "on schema failure for non-rejection rows, set `output` to `null`,
#  `result.schema_valid` to `false`, and `result.schema_error` to a
#  human-readable validation message"
def test_schema_failure_nulls_output_and_reports_the_error(run_cli, api):
    mock = api(lambda b, i: (200, completion(json.dumps({"code": "x"}))))
    r = run_cli(schema_cfg(mock.url), [ROW])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] is None
    assert row["result"]["schema_valid"] is False
    assert row["result"]["schema_error"] == "Missing required field: explanation"


# "for `greedy` and `sample`, schema failure sets `result.passed` to `false`"
def test_schema_failure_sets_passed_false_for_greedy(run_cli, api):
    mock = api(lambda b, i: (200, completion(json.dumps({"code": "x"}))))
    r = run_cli(schema_cfg(mock.url), [ROW])
    assert r.rows[0]["result"]["passed"] is False


def test_schema_failure_sets_passed_false_for_sample(run_cli, api):
    mock = api(lambda b, i: (200, completion(json.dumps({"code": "x"}))))
    cfg = schema_cfg(mock.url,
                     generation={"scheme": "sample", "temperature": 0.7,
                                 "max_tokens": 64})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is False


# "invalid JSON also counts as a schema failure"
def test_invalid_json_is_a_schema_failure(run_cli, api):
    mock = api(lambda b, i: (200, completion("Here is the code: not json")))
    r = run_cli(schema_cfg(mock.url), [ROW])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] is None
    assert row["result"]["schema_valid"] is False
    assert isinstance(row["result"]["schema_error"], str)
    assert row["result"]["schema_error"]


# T102: `schema_error` is absent on a passing row.
def test_schema_error_absent_on_success(run_cli, api):
    mock = api(lambda b, i: (200, completion(GOOD_JSON)))
    r = run_cli(schema_cfg(mock.url), [ROW])
    assert "schema_error" not in r.rows[0]["result"]


# "support JSON Schema draft 7 rules for `type` ..."
@pytest.mark.parametrize("schema,payload,valid", [
    ({"type": "object"}, {"a": 1}, True),
    ({"type": "object"}, [1, 2], False),
    ({"type": "array"}, [1, 2], True),
    ({"type": "string"}, "hi", True),
    ({"type": "string"}, 4, False),
    ({"type": "number"}, 4.5, True),
    ({"type": "integer"}, 4, True),
    ({"type": "integer"}, 4.5, False),
    ({"type": "integer"}, True, False),          # draft 7: booleans are not ints
    ({"type": "boolean"}, True, True),
    ({"type": "null"}, None, True),
    ({"type": ["string", "null"]}, None, True),
    ({"type": ["string", "null"]}, 3, False),
])
def test_schema_type_rules(run_cli, api, schema, payload, valid):
    mock = api(lambda b, i: (200, completion(json.dumps(payload))))
    r = run_cli(schema_cfg(mock.url, schema), [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["schema_valid"] is valid


# "... `required`, `properties`, `items`, `enum`, `minimum`, `maximum`,
#  `minLength`, `maxLength`, and `pattern`"
@pytest.mark.parametrize("schema,payload,valid", [
    ({"type": "object", "required": ["a"]}, {"a": 1}, True),
    ({"type": "object", "required": ["a", "b"]}, {"a": 1}, False),
    ({"type": "object", "properties": {"a": {"type": "string"}}},
     {"a": "s"}, True),
    ({"type": "object", "properties": {"a": {"type": "string"}}}, {"a": 1}, False),
    ({"type": "array", "items": {"type": "integer"}}, [1, 2, 3], True),
    ({"type": "array", "items": {"type": "integer"}}, [1, "x"], False),
    ({"enum": ["yes", "no"]}, "yes", True),
    ({"enum": ["yes", "no"]}, "maybe", False),
    ({"type": "number", "minimum": 5}, 5, True),
    ({"type": "number", "minimum": 5}, 4.9, False),
    ({"type": "number", "maximum": 10}, 10, True),
    ({"type": "number", "maximum": 10}, 10.5, False),
    ({"type": "string", "minLength": 3}, "abc", True),
    ({"type": "string", "minLength": 3}, "ab", False),
    ({"type": "string", "maxLength": 3}, "abcd", False),
    ({"type": "string", "pattern": "^[a-z]+$"}, "abc", True),
    ({"type": "string", "pattern": "^[a-z]+$"}, "ABC", False),
])
def test_schema_keyword_rules(run_cli, api, schema, payload, valid):
    mock = api(lambda b, i: (200, completion(json.dumps(payload))))
    r = run_cli(schema_cfg(mock.url, schema), [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["schema_valid"] is valid


def test_nested_properties_are_validated(run_cli, api):
    schema = {"type": "object", "required": ["outer"],
              "properties": {"outer": {"type": "object", "required": ["inner"],
                                       "properties": {"inner": {"type": "string"}}}}}
    mock = api(lambda b, i: (200, completion(json.dumps({"outer": {"inner": 3}}))))
    r = run_cli(schema_cfg(mock.url, schema), [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["schema_valid"] is False
    assert "inner" in r.rows[0]["result"]["schema_error"]


# "rejection sampling may use `output_schema` even when no separate
#  `evaluation` block is configured"
def test_rejection_accepts_output_schema_without_evaluation(run_cli, api):
    calls = {"n": 0}

    def responder(body, i):
        calls["n"] += 1
        text = "nope" if calls["n"] < 3 else GOOD_JSON
        return 200, completion(text)

    mock = api(responder)
    cfg = schema_cfg(mock.url,
                     generation={"scheme": "rejection", "temperature": 0.7,
                                 "n": 5, "max_tokens": 64})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] == {"code": json.loads(GOOD_JSON)}
    assert row["result"]["passed"] is True


# "for rejection sampling, schema failure is a failed attempt and may trigger
#  another try"
def test_rejection_retries_after_a_schema_failure(run_cli, api):
    calls = {"n": 0}

    def responder(body, i):
        calls["n"] += 1
        text = json.dumps({"code": "x"}) if calls["n"] < 3 else GOOD_JSON
        return 200, completion(text)

    mock = api(responder)
    cfg = schema_cfg(mock.url,
                     generation={"scheme": "rejection", "temperature": 0.7,
                                 "n": 5, "max_tokens": 64})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert mock.call_count == 3
    assert r.rows[0]["result"]["attempts"] == 3
    assert r.rows[0]["result"]["passed"] is True


def test_rejection_exhausting_attempts_on_schema_failures(run_cli, api):
    mock = api(lambda b, i: (200, completion(json.dumps({"code": "x"}))))
    cfg = schema_cfg(mock.url,
                     generation={"scheme": "rejection", "temperature": 0.7,
                                 "n": 3, "max_tokens": 64})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert mock.call_count == 3
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["schema_valid"] is False


# "when `output_schema` is present, parse the model response as JSON and
#  validate it before running any other evaluation"
# "if both schema validation and evaluation are configured, run schema
#  validation first and skip evaluation when schema validation fails"
def test_evaluation_is_skipped_when_schema_validation_fails(run_cli, api):
    def responder(body, i):
        system = (body.get("messages") or [{}])[0].get("content", "")
        if "evaluator" in system:
            return 200, completion("10")
        return 200, completion("definitely not json")

    mock = api(responder)
    cfg = schema_cfg(mock.url,
                     evaluation={"type": "llm_judge", "threshold": 7,
                                 "judge_prompt": {
                                     "system": "You are an evaluator. Score 0-10.",
                                     "user": "Rate: {__response__}"}})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert mock.call_count == 1, "the judge call ran despite a schema failure"
    assert r.rows[0]["result"]["schema_valid"] is False
    assert r.rows[0]["result"]["passed"] is False


def test_evaluation_runs_when_schema_validation_passes(run_cli, api):
    mock = api(lambda b, i: (200, completion(GOOD_JSON)))
    cfg = schema_cfg(mock.url,
                     evaluation={"type": "contains", "answer_field": "needle"})
    r = run_cli(cfg, [{"question": "q", "needle": "addition"}])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["result"]["schema_valid"] is True
    assert row["result"]["passed"] is True


def test_evaluation_failure_with_valid_schema_still_fails_the_row(run_cli, api):
    mock = api(lambda b, i: (200, completion(GOOD_JSON)))
    cfg = schema_cfg(mock.url,
                     evaluation={"type": "contains", "answer_field": "needle"})
    r = run_cli(cfg, [{"question": "q", "needle": "subtraction"}])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["result"]["schema_valid"] is True
    assert row["result"]["passed"] is False
    assert row["output"] == {"code": json.loads(GOOD_JSON)}


# T122: a schema failure lands in the summary's `failed` count.
def test_schema_failures_count_as_failed_in_the_summary(run_cli, api):
    mock = api(lambda b, i: (200, completion("not json")))
    r = run_cli(schema_cfg(mock.url), rows(3))
    assert r.code == 0, r.stderr
    assert r.summary["passed"] == 0
    assert r.summary["failed"] == 3


# ===========================================================================
# Resume
# ===========================================================================

def write_existing(path, count, *, output_field="solution", passed=True):
    lines = []
    for k in range(count):
        lines.append(json.dumps({
            "input": {"question": "q%d" % k, "answer": "5"},
            "output": {output_field: "old %d" % k},
            "result": {"passed": passed, "extracted_answer": "5", "attempts": 1},
            "meta": None,
        }))
    path.write_text("\n".join(lines) + "\n")


# "if `--resume` is set and the output file already exists, inspect the
#  existing output to determine how many input rows are already complete"
# "because outputs are written in input order, the existing line count gives
#  the number of leading rows to skip"
def test_resume_skips_leading_complete_rows(run_cli, api):
    mock = usage_api(api, "new\n#### 5")
    seed = run_cli(make_config(mock.url), [ROW])      # creates the output path
    assert seed.code == 0, seed.stderr
    write_existing(seed.out_path, 3)
    calls_before = mock.call_count

    r = _rerun(make_config(mock.url), rows(5), seed.out_path, ["--resume"])
    assert r.code == 0, r.stderr
    assert mock.call_count - calls_before == 2, "resume did not skip 3 rows"


def _rerun(config, data, out_path, extra, counter=[0]):
    """Run the CLI again against an existing output file."""
    counter[0] += 1
    base = out_path.parent
    cfg_path = base / ("resume%d.yaml" % counter[0])
    cfg_path.write_text(yaml.safe_dump(config))
    in_path = base / ("resume%d.jsonl" % counter[0])
    in_path.write_text("".join(json.dumps(r) + "\n" for r in data))
    cmd = [sys.executable, str(REJECTOR), "run", "--config", str(cfg_path),
           "--input", str(in_path), "--output", str(out_path)] + list(extra)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return CliResult(proc, out_path)


# "append new rows to the existing output file"
def test_resume_appends_to_the_existing_file(run_cli, api):
    mock = usage_api(api, "new\n#### 5")
    data = rows(5)
    seed = run_cli(make_config(mock.url), [ROW])
    write_existing(seed.out_path, 3)
    r = _rerun(make_config(mock.url), data, seed.out_path, ["--resume"])
    assert r.code == 0, r.stderr
    result_rows = r.rows
    assert len(result_rows) == 5
    assert result_rows[0]["output"] == {"solution": "old 0"}
    assert result_rows[3]["output"] == {"solution": "new\n#### 5"}
    assert result_rows[3]["input"]["question"] == "q3"


# "the summary covers only newly processed rows and includes `resumed_from`"
def test_resume_summary_covers_only_new_rows(run_cli, api):
    mock = usage_api(api, "new\n#### 5")
    data = rows(5)
    seed = run_cli(make_config(mock.url), [ROW])
    write_existing(seed.out_path, 3)
    r = _rerun(make_config(mock.url), data, seed.out_path, ["--resume"])
    assert r.code == 0, r.stderr
    assert r.summary["total"] == 2
    assert r.summary["resumed_from"] == 3
    assert r.summary["passed"] + r.summary["failed"] == 2


# T111: `--resume` with no existing output processes everything, resumed_from 0.
def test_resume_without_existing_output_processes_everything(run_cli, api):
    mock = usage_api(api, "new\n#### 5")
    r = run_cli(make_config(mock.url), rows(4), args=["--resume"])
    assert r.code == 0, r.stderr
    assert len(r.rows) == 4
    assert r.summary["resumed_from"] == 0
    assert r.summary["total"] == 4


# T111: without `--resume` the key is absent and a stale file is overwritten.
def test_resumed_from_absent_without_the_flag(run_cli, api):
    mock = usage_api(api, "new\n#### 5")
    r = run_cli(make_config(mock.url), rows(2))
    assert r.code == 0, r.stderr
    assert "resumed_from" not in r.summary


# "when a prior output row represents an incomplete multi-solution or
#  rejection result with fewer passing solutions than `num_solutions`, do not
#  skip that row; reprocess it from scratch"
def test_resume_reprocesses_an_incomplete_multi_solution_row(run_cli, api):
    mock = usage_api(api, "new\n#### 5")
    cfg = make_config(mock.url, num_solutions=3,
                      generation={"scheme": "sample", "temperature": 0.7,
                                  "max_tokens": 64})
    seed = run_cli(make_config(mock.url), [ROW])
    # Row 0 complete (3 solutions), row 1 incomplete (1 solution).
    lines = []
    for k, count in enumerate((3, 1)):
        lines.append(json.dumps({
            "input": {"question": "q%d" % k, "answer": "5"},
            "output": [{"solution": "old", "icl_setup": None}] * count,
            "result": {"passed": count, "failed": 0, "attempts": count},
            "meta": [],
        }))
    seed.out_path.write_text("\n".join(lines) + "\n")
    r = _rerun(cfg, rows(3), seed.out_path, ["--resume"])
    assert r.code == 0, r.stderr
    assert r.summary["resumed_from"] == 1, "the incomplete row was skipped"
    assert r.summary["total"] == 2
    assert len(r.rows) == 3
    assert r.rows[0]["output"][0]["solution"] == "old"
    assert len(r.rows[1]["output"]) == 3


# T110: an exhausted single-solution rejection row is incomplete too.
def test_resume_reprocesses_a_failed_rejection_row(run_cli, api):
    mock = usage_api(api, "new\n#### 5")
    cfg = make_config(mock.url,
                      generation={"scheme": "rejection", "temperature": 0.7,
                                  "n": 3, "max_tokens": 64})
    seed = run_cli(make_config(mock.url), [ROW])
    lines = [
        json.dumps({"input": {"question": "q0", "answer": "5"},
                    "output": {"solution": "old"},
                    "result": {"passed": True, "extracted_answer": "5",
                               "attempts": 1}, "meta": None}),
        json.dumps({"input": {"question": "q1", "answer": "5"},
                    "output": None,
                    "result": {"passed": False, "extracted_answer": None,
                               "attempts": 3}, "meta": []}),
    ]
    seed.out_path.write_text("\n".join(lines) + "\n")
    r = _rerun(cfg, rows(3), seed.out_path, ["--resume"])
    assert r.code == 0, r.stderr
    assert r.summary["resumed_from"] == 1
    assert r.rows[1]["output"] == {"solution": "new\n#### 5"}


# T113: a half-written trailing line is not a complete row.
def test_resume_drops_a_truncated_trailing_line(run_cli, api):
    mock = usage_api(api, "new\n#### 5")
    seed = run_cli(make_config(mock.url), [ROW])
    write_existing(seed.out_path, 2)
    seed.out_path.write_text(seed.out_path.read_text() + '{"input": {"que')
    r = _rerun(make_config(mock.url), rows(4), seed.out_path, ["--resume"])
    assert r.code == 0, r.stderr
    assert r.summary["resumed_from"] == 2
    assert len(r.rows) == 4


# "for multi-task configs, apply resume separately per task output file"
def test_resume_applies_per_task_output_file(run_multi, api):
    mock = usage_api(api, "new\n#### 5")
    task = {"prompt": {"user": "{question}"}, "output_field": "solution",
            "generation": {"scheme": "greedy", "max_tokens": 16}}
    cfg = make_multi_config(mock.url, {"a": copy.deepcopy(task),
                                       "b": copy.deepcopy(task)})
    first = run_multi(cfg, {"a": rows(4), "b": rows(4)})
    assert first.code == 0, first.stderr
    # Trim task a's output to 1 row; leave b's four rows complete.
    a_lines = first.path("a").read_text().splitlines()
    first.path("a").write_text(a_lines[0] + "\n")
    calls_before = mock.call_count

    cmd = [sys.executable, str(REJECTOR), "run",
           "--config", str(first.data_dir.parent / "config.yaml"),
           "--input", "a=%s" % first.data_dir.joinpath("a.jsonl"),
           "--input", "b=%s" % first.data_dir.joinpath("b.jsonl"),
           "--output", str(first.out_dir), "--resume"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout.splitlines()[-1])
    # a resumes from 1 and redoes 3; b resumes from 4 and redoes nothing.
    assert summary["tasks"]["a"]["resumed_from"] == 1
    assert summary["tasks"]["b"]["resumed_from"] == 4
    assert summary["total"] == 3
    assert mock.call_count - calls_before == 3
    assert len(first.path("a").read_text().splitlines()) == 4


# T112: per-task `resumed_from` alongside the aggregate.
def test_multi_task_resumed_from_is_reported_per_task(run_multi, api):
    mock = usage_api(api, "new\n#### 5")
    task = {"prompt": {"user": "{question}"}, "output_field": "solution",
            "generation": {"scheme": "greedy", "max_tokens": 16}}
    cfg = make_multi_config(mock.url, {"a": copy.deepcopy(task),
                                       "b": copy.deepcopy(task)})
    r = run_multi(cfg, {"a": rows(3), "b": rows(3)}, args=["--resume"])
    assert r.code == 0, r.stderr
    assert r.summary["resumed_from"] == 0
    assert r.summary["tasks"]["a"]["resumed_from"] == 0
    assert r.summary["tasks"]["b"]["resumed_from"] == 0


# ===========================================================================
# Dry Run
# ===========================================================================

# "validate config and inputs, but make no API calls"
# "print the estimate JSON to stdout and exit `0`"
def test_dry_run_makes_no_api_calls(run_cli, api):
    mock = usage_api(api)
    r = run_cli(make_config(mock.url), rows(4), args=["--dry-run"])
    assert r.code == 0, r.stderr
    assert mock.call_count == 0
    assert isinstance(r.summary, dict)


def test_dry_run_still_validates_the_config(run_cli, api):
    mock = usage_api(api)
    cfg = make_config(mock.url, output_field=None)
    r = run_cli(cfg, rows(2), args=["--dry-run"])
    assert r.code == 1
    assert "output_field" in r.stderr


def test_dry_run_still_validates_the_input_rows(run_cli, api):
    mock = usage_api(api)
    r = run_cli(make_config(mock.url), [{"nope": 1}], args=["--dry-run"])
    assert r.code == 1


# "count input rows per task"
def test_dry_run_counts_input_rows_per_task(run_multi, api):
    mock = usage_api(api)
    task = {"prompt": {"user": "{question}"}, "output_field": "solution",
            "generation": {"scheme": "greedy", "max_tokens": 100}}
    cfg = make_multi_config(mock.url, {"a": copy.deepcopy(task),
                                       "b": copy.deepcopy(task)})
    r = run_multi(cfg, {"a": rows(4), "b": rows(6)}, args=["--dry-run"])
    assert r.code == 0, r.stderr
    est = r.summary
    assert est["tasks"]["a"]["inputs"] == 4
    assert est["tasks"]["b"]["inputs"] == 6
    assert est["total_inputs"] == 10


# "estimate prompt tokens as `average prompt word count * 1.33`"
# "estimate total tokens as estimated prompt tokens plus `max_tokens`"
def test_dry_run_token_estimates(run_cli, api):
    mock = usage_api(api)
    cfg = make_config(mock.url, prompt={"user": "one two three {question}"},
                      generation={"scheme": "greedy", "max_tokens": 100})
    data = [{"question": "alpha", "answer": "5"},
            {"question": "beta gamma", "answer": "5"}]
    r = run_cli(cfg, data, args=["--dry-run"])
    assert r.code == 0, r.stderr
    est = r.summary["tasks"]["math_solve"]
    avg_words = (4 + 5) / 2
    assert est["inputs"] == 2
    assert est["est_prompt_tokens"] == round(2 * avg_words * 1.33)
    assert est["est_completion_tokens"] == 2 * 100
    assert est["est_total_tokens"] == est["est_prompt_tokens"] + 200


# "estimate cost using the configured cost rates"
def test_dry_run_cost_estimate(run_cli, api):
    mock = usage_api(api)
    cfg = limited(mock.url, cost=dict(COST),
                  prompt={"user": "one two three {question}"},
                  generation={"scheme": "greedy", "max_tokens": 100})
    data = [{"question": "alpha", "answer": "5"}] * 2
    r = run_cli(cfg, data, args=["--dry-run"])
    assert r.code == 0, r.stderr
    est = r.summary["tasks"]["math_solve"]
    expected = (est["est_prompt_tokens"] / 1000 * 0.01
                + est["est_completion_tokens"] / 1000 * 0.03)
    assert est["est_cost"] == pytest.approx(expected, abs=1e-4)
    assert r.summary["est_total_cost"] == pytest.approx(expected, abs=1e-4)


# "estimate time in minutes as `total_inputs * avg_attempts / rpm`, where
#  `avg_attempts` is `1` for `greedy` and `sample`"
def test_dry_run_time_estimate_for_greedy(run_cli, api):
    mock = usage_api(api)
    cfg = limited(mock.url, rate_limits={"rpm": 100})
    r = run_cli(cfg, rows(250), args=["--dry-run"])
    assert r.code == 0, r.stderr
    assert r.summary["est_time_minutes"] == pytest.approx(250 * 1 / 100)


# "... and `n` for rejection worst-case planning"
def test_dry_run_time_estimate_for_rejection(run_cli, api):
    mock = usage_api(api)
    cfg = limited(mock.url, rate_limits={"rpm": 100},
                  generation={"scheme": "rejection", "temperature": 0.7,
                              "n": 5, "max_tokens": 64})
    r = run_cli(cfg, rows(200), args=["--dry-run"])
    assert r.code == 0, r.stderr
    assert r.summary["est_time_minutes"] == pytest.approx(200 * 5 / 100)


# "prefer precision over rounding"
def test_dry_run_time_estimate_keeps_fractional_precision(run_cli, api):
    mock = usage_api(api)
    cfg = limited(mock.url, rate_limits={"rpm": 60})
    r = run_cli(cfg, rows(7), args=["--dry-run"])
    assert r.code == 0, r.stderr
    value = r.summary["est_time_minutes"]
    assert value == pytest.approx(7 / 60)
    assert value != round(value, 1), "the estimate was rounded away"


# The spec's estimate shape.
def test_dry_run_output_shape(run_cli, api):
    mock = usage_api(api)
    cfg = limited(mock.url, cost=dict(COST), rate_limits={"rpm": 100})
    r = run_cli(cfg, rows(3), args=["--dry-run"])
    assert r.code == 0, r.stderr
    est = r.summary
    assert set(est) >= {"tasks", "total_inputs", "est_total_tokens",
                        "est_total_cost", "est_time_minutes"}
    task_est = est["tasks"]["math_solve"]
    assert set(task_est) >= {"inputs", "est_prompt_tokens",
                             "est_completion_tokens", "est_total_tokens",
                             "est_cost"}
    assert est["est_total_tokens"] == task_est["est_total_tokens"]


def test_dry_run_writes_no_output_file(run_cli, api):
    mock = usage_api(api)
    r = run_cli(make_config(mock.url), rows(3), args=["--dry-run"])
    assert r.code == 0, r.stderr
    assert not r.out_path.exists() or r.out_path.read_text() == ""


# ===========================================================================
# Progress Reporting
# ===========================================================================

PROGRESS_RE = re.compile(
    r"^\[(\d+)/(\d+)\] (\d+)% complete"
    r"(?: \| (\d+) passed, (\d+) failed)?"
    r" \| ([\d.]+) rpm"
    r"(?: \| \$([\d.]+) spent)?"
    r" \| ETA: (\d+)s$")


def progress_lines(stderr):
    return [l for l in stderr.splitlines() if l.startswith("[")]


# "print progress updates to stderr every 5 seconds or every 10% of total
#  inputs, whichever comes first"
def test_progress_prints_updates_to_stderr(run_cli, api):
    mock = usage_api(api, delay=0.02)
    r = run_cli(make_config(mock.url), rows(20), args=["--progress"])
    assert r.code == 0, r.stderr
    lines = progress_lines(r.stderr)
    assert lines, r.stderr
    for line in lines:
        assert PROGRESS_RE.match(line), line


def test_progress_is_not_printed_without_the_flag(run_cli, api):
    mock = usage_api(api)
    r = run_cli(make_config(mock.url), rows(20))
    assert r.code == 0, r.stderr
    assert progress_lines(r.stderr) == []


# "[50/100] 50% complete | ... " — the counter tracks completed inputs.
def test_progress_counts_reach_the_total(run_cli, api):
    mock = usage_api(api, delay=0.01)
    r = run_cli(make_config(mock.url), rows(20), args=["--progress"])
    assert r.code == 0, r.stderr
    last = progress_lines(r.stderr)[-1]
    match = PROGRESS_RE.match(last)
    assert match, last
    assert match.group(1) == "20"
    assert match.group(2) == "20"
    assert match.group(3) == "100"


# "include `passed` / `failed` counts only when evaluation is configured"
def test_progress_includes_passed_failed_with_evaluation(run_cli, api):
    mock = usage_api(api, delay=0.01)
    r = run_cli(make_config(mock.url), rows(10), args=["--progress"])
    assert r.code == 0, r.stderr
    last = progress_lines(r.stderr)[-1]
    assert "passed" in last and "failed" in last
    match = PROGRESS_RE.match(last)
    assert match.group(4) is not None


# "if no evaluation is configured, omit the passed/failed field"
def test_progress_omits_passed_failed_without_evaluation(run_cli, api):
    mock = usage_api(api, delay=0.01)
    cfg = make_config(mock.url, evaluation=None)
    r = run_cli(cfg, rows(10), args=["--progress"])
    assert r.code == 0, r.stderr
    for line in progress_lines(r.stderr):
        assert "passed" not in line, line
        assert PROGRESS_RE.match(line), line


# "include `$... spent` only when cost tracking is configured"
def test_progress_includes_cost_when_configured(run_cli, api):
    mock = usage_api(api, prompt_tokens=1000, completion_tokens=1000, delay=0.01)
    cfg = limited(mock.url, cost=dict(COST))
    r = run_cli(cfg, rows(10), args=["--progress"])
    assert r.code == 0, r.stderr
    last = progress_lines(r.stderr)[-1]
    assert " spent" in last, last
    assert PROGRESS_RE.match(last), last


# "if cost tracking is disabled, omit the cost field"
def test_progress_omits_cost_when_not_configured(run_cli, api):
    mock = usage_api(api, delay=0.01)
    r = run_cli(make_config(mock.url), rows(10), args=["--progress"])
    assert r.code == 0, r.stderr
    for line in progress_lines(r.stderr):
        assert "spent" not in line, line


# The summary still goes to stdout while progress goes to stderr.
def test_progress_does_not_pollute_stdout(run_cli, api):
    mock = usage_api(api, delay=0.01)
    r = run_cli(make_config(mock.url), rows(10), args=["--progress"])
    assert r.code == 0, r.stderr
    assert r.summary["total"] == 10
    assert "complete |" not in r.stdout


# T121: one display covering every executed task's rows.
def test_progress_total_spans_all_tasks(run_multi, api):
    mock = usage_api(api, delay=0.01)
    task = {"prompt": {"user": "{question}"}, "output_field": "solution",
            "generation": {"scheme": "greedy", "max_tokens": 16}}
    cfg = make_multi_config(mock.url, {"a": copy.deepcopy(task),
                                       "b": copy.deepcopy(task)})
    r = run_multi(cfg, {"a": rows(6), "b": rows(4)}, args=["--progress"])
    assert r.code == 0, r.stderr
    lines = progress_lines(r.stderr)
    assert lines, r.stderr
    assert PROGRESS_RE.match(lines[-1]).group(2) == "10"


# ===========================================================================
# Cross-feature integration
# ===========================================================================

def test_dry_run_and_resume_are_independent_flags(run_cli, api):
    mock = usage_api(api)
    r = run_cli(make_config(mock.url), rows(3), args=["--dry-run", "--resume"])
    assert r.code == 0, r.stderr
    assert mock.call_count == 0


def test_schema_validation_with_cost_and_progress(run_cli, api):
    mock = api(lambda b, i: (200, completion(GOOD_JSON, prompt_tokens=1000,
                                             completion_tokens=1000)))
    cfg = schema_cfg(mock.url)
    cfg["task"]["cost"] = dict(COST)
    r = run_cli(cfg, rows(4), args=["--progress"])
    assert r.code == 0, r.stderr
    assert r.summary["cost"]["total"] == pytest.approx(4 * 0.04)
    assert all(row["result"]["schema_valid"] for row in r.rows)
