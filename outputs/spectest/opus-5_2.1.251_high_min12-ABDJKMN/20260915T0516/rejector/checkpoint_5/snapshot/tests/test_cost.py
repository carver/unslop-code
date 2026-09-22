"""Part 5: cost accounting and the budget stop."""
import pytest

import rejector
from conftest import (agentic_config, cost_block, judge_task, limits_block,
                      make_config, make_multi_config, static_map_tool)
from mock_api import MockAPI, agentic_turns, always, by_text


RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
# The mock's default usage block: 45 prompt + 120 completion tokens.
CALL_COST = 45 / 1000.0 * 0.01 + 120 / 1000.0 * 0.03      # 0.00405


# --------------------------------------------------------------- config ---

# Spec: "defaults:\n  cost:\n    prompt_cost_per_1k: 0.01\n
#        completion_cost_per_1k: 0.03\n    budget: 50.0"
# Context: Cost Tracking / Configuration.
def test_cost_block_is_accepted(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   cost=cost_block(0.01, 0.03, budget=50.0)),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert "cost" in run.summary


# Spec: "defaults.cost is merged into each task the same way earlier
#        checkpoints merged prompt, generation, and evaluation"
# Context: Cost Tracking / multi-task configs.
def test_defaults_cost_merges_into_each_task():
    config = make_multi_config(defaults={"cost": cost_block(0.01, 0.03, 50.0)})
    _multi, specs = rejector.split_config(config)
    for _name, task in specs:
        assert task["cost"] == {"prompt_cost_per_1k": 0.01,
                                "completion_cost_per_1k": 0.03,
                                "budget": 50.0}


# Spec: "Per-task `cost` keys override only the keys they specify."
# Context: the per-task example sets both rates but not `budget`.
def test_per_task_cost_overrides_only_named_keys():
    config = make_multi_config(
        defaults={"cost": cost_block(0.01, 0.03, 50.0)},
        tasks={"code_gen": {"prompt": {"user": "{question}"},
                            "generation": {"scheme": "greedy"},
                            "cost": {"prompt_cost_per_1k": 0.005,
                                     "completion_cost_per_1k": 0.015}}})
    _multi, specs = rejector.split_config(config)
    assert specs[0][1]["cost"] == {"prompt_cost_per_1k": 0.005,
                                   "completion_cost_per_1k": 0.015,
                                   "budget": 50.0}


# Spec: "--budget <float>"
# Context: Cost Tracking / CLI flag.
def test_budget_cli_flag_is_accepted(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, cost=cost_block()),
                       [{"question": "q", "answer": "5"}],
                       args=["--budget", "12.5"])
    assert run.returncode == 0, run.stderr
    assert run.summary["cost"]["budget"] == 12.5


# ------------------------------------------------------------- formula ---

# Spec: "(prompt_tokens / 1000 * prompt_cost_per_1k) +
#        (completion_tokens / 1000 * completion_cost_per_1k)"
# Context: Cost Tracking / Cost per API call.
def test_cost_per_call_formula():
    rates = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
    prompt, completion = rejector.call_cost(rates, 1000, 2000)
    assert prompt == pytest.approx(0.01)
    assert completion == pytest.approx(0.06)


# Spec: "track prompt cost, completion cost, and total cost"
# Context: Cost Tracking / Rules.
def test_summary_reports_prompt_completion_and_total(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(4)]
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, cost=cost_block()), rows)
    assert run.returncode == 0, run.stderr
    cost = run.summary["cost"]
    assert cost["prompt"] == pytest.approx(4 * 45 / 1000.0 * 0.01)
    assert cost["completion"] == pytest.approx(4 * 120 / 1000.0 * 0.03)
    assert cost["total"] == pytest.approx(4 * CALL_COST)


# Spec: the summary shape's budget fields.
# Context: "budget": 50.0, "budget_remaining": 37.55, "budget_exceeded": false
def test_summary_budget_fields(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(2)]
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   cost=cost_block(budget=50.0)), rows)
    assert run.returncode == 0, run.stderr
    cost = run.summary["cost"]
    assert cost["budget"] == 50.0
    assert cost["budget_exceeded"] is False
    assert cost["budget_remaining"] == pytest.approx(50.0 - cost["total"])
    assert set(cost) == {"total", "prompt", "completion", "budget",
                         "budget_remaining", "budget_exceeded"}


# Spec: "if no cost configuration is present, omit the `cost` field from the
#        summary"
# Context: Cost Tracking / Rules.
def test_cost_field_omitted_without_cost_config(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert "cost" not in run.summary


# Spec: when no budget is configured the budget keys have nothing to report.
def test_budget_keys_absent_without_a_budget(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, cost=cost_block()),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    cost = run.summary["cost"]
    assert cost["budget"] is None
    assert cost["budget_remaining"] is None
    assert cost["budget_exceeded"] is False


# Spec: "include judge calls"
# Context: Cost Tracking / Rules. Two API calls per row: generation + judge.
def test_judge_calls_are_included_in_cost(run_tool):
    rows = [{"prompt_text": "p", "criteria": "good"}]
    responder = by_text([("Rate this response", "9")], default="an answer")
    with MockAPI(responder) as api:
        run = run_tool({"task": dict(judge_task(), name="j", api_url=api.url,
                                     model="gpt-4", rpm=60,
                                     cost=cost_block())}, rows)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2
    assert run.summary["cost"]["total"] == pytest.approx(2 * CALL_COST)


# Spec: "include ... every agentic iteration"
# Context: Cost Tracking / Rules.
def test_every_agentic_iteration_is_included_in_cost(run_tool):
    rows = [{"question": "q", "answer": "142"}]
    steps = [[("lookup", {"key": "employees"})], "#### 142"]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url, tools=[static_map_tool()],
                                      cost=cost_block()), rows)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2
    assert run.summary["cost"]["total"] == pytest.approx(2 * CALL_COST)


# Spec: "track ... across all tasks"
# Context: Cost Tracking / Rules; one cost block covers the whole run.
def test_cost_is_tracked_across_all_tasks(multi):
    config = make_multi_config(defaults={"cost": cost_block()})
    with MockAPI(always("#### 5")) as api:
        config["defaults"]["api_url"] = api.url
        run = multi.run(config, {"gsm8k": [{"question": "q", "answer": "5"}],
                                 "mmlu": [{"question": "q", "answer": "A"}]})
    assert run.returncode == 0, run.stderr
    assert run.summary["cost"]["total"] == pytest.approx(2 * CALL_COST)


# ------------------------------------------------------ budget exhaustion ---

# Spec: "when `budget` is configured and the running total reaches or exceeds
#        it: stop sending new requests immediately, let in-flight requests
#        finish, write completed results, print the summary, and exit `0`"
# Context: Cost Tracking / Rules, plus the "Budget exceeded" example where
# `budget: 1.00` and the running total reaches `$1.02`.
def test_budget_stop_writes_partial_output_and_exits_zero(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(20)]
    # One call costs 45/1000*10 + 120/1000*10 = 1.65, past a 1.00 budget.
    cost = {"prompt_cost_per_1k": 10.0, "completion_cost_per_1k": 10.0,
            "budget": 1.00}
    with MockAPI(always("#### 5"), service_seconds=0.02) as api:
        run = run_tool(make_config(api_url=api.url, cost=cost, rpm=6000,
                                   rate_limits=limits_block(max_concurrent=1)),
                       rows)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 1
    assert run.summary["cost"]["budget_exceeded"] is True
    assert run.summary["cost"]["total"] == pytest.approx(1.65)
    assert len(run.rows) == 1


# Spec: "budget exhaustion is not an error; partial output is valid"
# Context: the completed rows are ordinary, fully formed result rows.
def test_partial_output_rows_are_well_formed(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(10)]
    cost = {"prompt_cost_per_1k": 10.0, "completion_cost_per_1k": 10.0,
            "budget": 1.00}
    with MockAPI(always("#### 5"), service_seconds=0.02) as api:
        run = run_tool(make_config(api_url=api.url, cost=cost, rpm=6000,
                                   rate_limits=limits_block(max_concurrent=1)),
                       rows)
    assert run.returncode == 0, run.stderr
    assert run.summary["total"] == len(run.rows)
    for record in run.rows:
        assert record["result"]["passed"] is True
        assert record["output"]["solution"] == "#### 5"


# Spec: "budget_remaining" once the budget is blown.
def test_budget_remaining_when_exceeded(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(4)]
    cost = {"prompt_cost_per_1k": 10.0, "completion_cost_per_1k": 10.0,
            "budget": 1.00}
    with MockAPI(always("#### 5"), service_seconds=0.02) as api:
        run = run_tool(make_config(api_url=api.url, cost=cost, rpm=6000,
                                   rate_limits=limits_block(max_concurrent=1)),
                       rows)
    assert run.returncode == 0, run.stderr
    summary = run.summary["cost"]
    assert summary["budget_remaining"] == pytest.approx(1.00 - summary["total"])


# Spec: "stop sending new requests immediately, let in-flight requests finish"
# Context: with several requests in flight, every started request still lands.
def test_in_flight_requests_finish_after_the_budget_trips(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(20)]
    cost = {"prompt_cost_per_1k": 10.0, "completion_cost_per_1k": 10.0,
            "budget": 1.00}
    with MockAPI(always("#### 5"), service_seconds=0.2) as api:
        run = run_tool(make_config(api_url=api.url, cost=cost, rpm=6000,
                                   rate_limits=limits_block(max_concurrent=4)),
                       rows)
    assert run.returncode == 0, run.stderr
    # The four concurrent requests were all in flight when the budget tripped.
    assert api.call_count == 4
    assert len(run.rows) == 4
    assert run.summary["cost"]["budget_exceeded"] is True


# Spec: a budget that is never reached does not stop anything.
def test_budget_not_reached_runs_every_row(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(6)]
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   cost=cost_block(budget=50.0)), rows)
    assert run.returncode == 0, run.stderr
    assert len(run.rows) == 6
    assert run.summary["cost"]["budget_exceeded"] is False
