"""Spec section: Cost Tracking (per-call cost, totals, budget)."""
from __future__ import annotations

import copy

import pytest

from conftest import (AGENTIC_ROW, GSM8K_TASK, LOOKUP_TOOL, MMLU_TASK,
                      agentic_config, agentic_replies, base_config,
                      judge_responder, multi_config, rows_of)
from mock_server import MockAPI, always, completion

PROMPT_RATE = 0.01
COMPLETION_RATE = 0.03
COST = {"prompt_cost_per_1k": PROMPT_RATE,
        "completion_cost_per_1k": COMPLETION_RATE}


def call_cost(prompt_tokens, completion_tokens, *, prompt_rate=PROMPT_RATE,
              completion_rate=COMPLETION_RATE):
    return (prompt_tokens / 1000 * prompt_rate
            + completion_tokens / 1000 * completion_rate)


# ---------------------------------------------------------------------------
# Phrase: "Cost per API call: (prompt_tokens / 1000 * prompt_cost_per_1k) +
#          (completion_tokens / 1000 * completion_cost_per_1k)"
# Context: Cost Tracking.  Three rows with known usage.
# ---------------------------------------------------------------------------
def test_cost_per_call_formula(run_tool, write_config, write_input):
    with MockAPI(always("#### 5", prompt_tokens=200,
                        completion_tokens=400)) as api:
        cfg = write_config(base_config(api.url, cost=dict(COST)))
        data = write_input(rows_of(3))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    cost = res.summary["cost"]
    assert cost["prompt"] == pytest.approx(3 * 200 / 1000 * PROMPT_RATE)
    assert cost["completion"] == pytest.approx(3 * 400 / 1000 * COMPLETION_RATE)
    assert cost["total"] == pytest.approx(3 * call_cost(200, 400))


# ---------------------------------------------------------------------------
# Phrase: "track prompt cost, completion cost, and total cost across all tasks;
#          report them to at least four decimal places"
# Context: Cost Tracking.  A single cheap call must not round away to 0.0.
# ---------------------------------------------------------------------------
def test_cost_keeps_four_decimal_places(run_tool, write_config, write_input):
    with MockAPI(always("#### 5", prompt_tokens=45,
                        completion_tokens=120)) as api:
        cfg = write_config(base_config(api.url, cost=dict(COST)))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    cost = res.summary["cost"]
    expected = call_cost(45, 120)          # 0.00405
    assert cost["total"] == pytest.approx(expected, abs=1e-6)
    assert cost["total"] != 0.0


# ---------------------------------------------------------------------------
# Phrase: "Summary shape: cost.total / prompt / completion / budget /
#          budget_remaining / budget_exceeded"
# Context: Cost Tracking.
# ---------------------------------------------------------------------------
def test_cost_summary_shape(run_tool, write_config, write_input):
    with MockAPI(always("#### 5", prompt_tokens=100,
                        completion_tokens=100)) as api:
        cfg = write_config(base_config(api.url,
                                       cost=dict(COST, budget=50.0)))
        data = write_input(rows_of(2))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    cost = res.summary["cost"]
    for key in ("total", "prompt", "completion", "budget",
                "budget_remaining", "budget_exceeded"):
        assert key in cost, cost
    assert cost["budget"] == 50.0
    assert cost["budget_exceeded"] is False
    assert cost["budget_remaining"] == pytest.approx(50.0 - cost["total"])


# ---------------------------------------------------------------------------
# Phrase: "if no cost configuration is present, omit the `cost` field from the
#          summary"
# Context: Cost Tracking.
# ---------------------------------------------------------------------------
def test_cost_field_omitted_without_cost_config(run_tool, write_config,
                                                write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(2))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert "cost" not in res.summary, res.summary


# ---------------------------------------------------------------------------
# Phrase: "CLI flag: --budget <float>"
# Context: Cost Tracking.
# ---------------------------------------------------------------------------
def test_budget_flag_is_accepted(run_tool, write_config, write_input):
    with MockAPI(always("#### 5", prompt_tokens=100,
                        completion_tokens=100)) as api:
        cfg = write_config(base_config(api.url, cost=dict(COST)))
        data = write_input(rows_of(2))
        res = run_tool(cfg, data, extra=["--budget", "12.5"])
    assert res.returncode == 0, res
    assert res.summary["cost"]["budget"] == 12.5


# ---------------------------------------------------------------------------
# Phrase: "For multi-task configs, `defaults.cost` is merged into each task the
#          same way earlier checkpoints merged `prompt`..."
# Phrase: "Per-task `cost` keys override only the keys they specify."
# Context: Cost Tracking.  gsm8k uses the defaults; mmlu halves the prompt rate
# and keeps the default completion rate.
# ---------------------------------------------------------------------------
def test_defaults_cost_merges_and_per_task_overrides(run_tool, write_config,
                                                     write_input, workdir):
    with MockAPI(always("#### 5", prompt_tokens=1000,
                        completion_tokens=1000)) as api:
        tasks = {"gsm8k": copy.deepcopy(GSM8K_TASK),
                 "mmlu": dict(copy.deepcopy(MMLU_TASK),
                              cost={"prompt_cost_per_1k": 0.005})}
        cfg = write_config(multi_config(api.url, tasks,
                                        defaults={"cost": dict(COST)}))
        a = write_input(rows_of(1), name="a.jsonl")
        b = write_input([{"question": "q", "a": "1", "b": "2", "c": "3",
                          "d": "4", "answer": "A"}], name="b.jsonl")
        res = run_tool(cfg, [f"gsm8k={a}", f"mmlu={b}"],
                       output=str(workdir / "out"))
    assert res.returncode == 0, res
    cost = res.summary["cost"]
    # gsm8k: 0.01 + 0.03; mmlu: 0.005 + 0.03 (completion rate inherited).
    assert cost["prompt"] == pytest.approx(0.01 + 0.005)
    assert cost["completion"] == pytest.approx(0.03 + 0.03)
    assert cost["total"] == pytest.approx(0.075)


# ---------------------------------------------------------------------------
# Phrase: "include judge calls and every agentic iteration"
# Context: Cost Tracking.  Judge replies report their own usage (11/2).
# ---------------------------------------------------------------------------
def test_cost_includes_judge_calls(run_tool, write_config, write_input):
    evaluation = {
        "type": "llm_judge",
        "judge_prompt": {
            "system": "You are a quality evaluator. Respond with only a "
                      "single integer from 1 to 10.",
            "user": "Rate this response:\n{__response__}\n\nScore:",
        },
        "threshold": 7,
        "extract": "first_number",
        "answer_field": None,
    }
    with MockAPI(judge_responder()) as api:
        cfg = write_config(base_config(
            api.url, evaluation=evaluation, output_field="response",
            prompt={"system": "You are a writer.", "user": "{prompt_text}"},
            cost=dict(COST)))
        data = write_input([{"prompt_text": "p0"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    # generation usage 45/120 plus judge usage 11/2.
    expected = call_cost(45, 120) + call_cost(11, 2)
    assert res.summary["cost"]["total"] == pytest.approx(expected, abs=1e-8)


def test_cost_includes_every_agentic_iteration(run_tool, write_config,
                                               write_input):
    script = [[("lookup", {"key": "revenue_q1"})],
              [("lookup", {"key": "revenue_q2"})],
              "#### 2730000"]
    with MockAPI(agentic_replies(script)) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL],
                                          cost=dict(COST)))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 3
    # two tool-call replies (45/20) and one final answer (45/120)
    expected = 2 * call_cost(45, 20) + call_cost(45, 120)
    assert res.summary["cost"]["total"] == pytest.approx(expected, abs=1e-8)


# ---------------------------------------------------------------------------
# Phrase: "when `budget` is configured and the running total reaches or exceeds
#          it: stop sending new requests immediately, let in-flight requests
#          finish, write completed results, print the summary, and exit `0`"
# Phrase: "if `budget: 1.00` and the running total reaches `$1.02` ... print
#          `cost.budget_exceeded: true` ... exit `0`"
# Context: Cost Tracking / Examples.  Each call costs $0.51, so the budget is
# blown after two calls and the remaining rows are never sent.
# ---------------------------------------------------------------------------
def test_budget_stops_the_run_and_exits_zero(run_tool, write_config,
                                             write_input):
    with MockAPI(always("#### 5", prompt_tokens=1000,
                        completion_tokens=10000), delay=0.05) as api:
        cfg = write_config(base_config(
            api.url, rate_limits={"max_concurrent": 1},
            cost=dict(COST, budget=1.00)))
        data = write_input(rows_of(20))
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls < 20, calls
    summary = res.summary
    assert summary["cost"]["budget_exceeded"] is True
    assert summary["cost"]["total"] >= 1.00
    assert len(res.rows) == summary["total"]
    assert len(res.rows) < 20


# Context: Cost Tracking - "budget exhaustion is not an error; partial output
# is valid": the rows that did complete are written and well formed.
def test_budget_partial_output_is_valid(run_tool, write_config, write_input):
    with MockAPI(always("#### 5", prompt_tokens=1000,
                        completion_tokens=10000), delay=0.05) as api:
        cfg = write_config(base_config(
            api.url, rate_limits={"max_concurrent": 1},
            cost=dict(COST, budget=0.62)))
        data = write_input(rows_of(10))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.stderr.strip() == "", res.stderr
    rows = res.rows
    assert 1 <= len(rows) < 10
    for i, row in enumerate(rows):
        assert row["input"]["question"] == f"q{i}"
        assert row["output"]["solution"] == "#### 5"
        assert row["result"]["passed"] is True


# Context: Cost Tracking - a run that stays inside its budget reports
# `budget_exceeded: false` and a positive remainder.
def test_budget_not_exceeded(run_tool, write_config, write_input):
    with MockAPI(always("#### 5", prompt_tokens=100,
                        completion_tokens=100)) as api:
        cfg = write_config(base_config(api.url,
                                       cost=dict(COST, budget=100.0)))
        data = write_input(rows_of(3))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    cost = res.summary["cost"]
    assert cost["budget_exceeded"] is False
    assert cost["budget_remaining"] == pytest.approx(100.0 - cost["total"])
    assert len(res.rows) == 3
