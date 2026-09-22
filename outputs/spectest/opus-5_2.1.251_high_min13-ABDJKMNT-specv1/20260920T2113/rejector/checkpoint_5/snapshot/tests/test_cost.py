"""Cost tracking: the per-call charge, the summary's `cost` object, and merging."""

from __future__ import annotations

import pytest

from rejlib.config import load_config
from rejlib.errors import ConfigError
from tests.conftest import (
    agentic_config, answering, judge_responder, lookup_then_answer, multi_config,
    numbered_rows, task_config,
)

#: The spec's example rates, and the usage every fake reply reports below.
RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
USAGE = {"prompt_tokens": 1000, "completion_tokens": 500}
#: 1000/1000 * 0.01 + 500/1000 * 0.03
PER_CALL = 0.025


def load(cli, config, **overrides):
    return load_config(cli.write_config(config), overrides)


def cost_run(cli, api, rows, **cost):
    server = api(answering(**USAGE))
    config = task_config(api_url=server.url, rpm=600, cost={**RATES, **cost})
    return cli.run(config, rows)


# "defaults:\n  cost:\n    prompt_cost_per_1k: 0.01\n    completion_cost_per_1k: 0.03
#   \n    budget: 50.0"
def test_cost_section_loads(cli):
    config = multi_config("gsm8k", defaults={"cost": {**RATES, "budget": 50.0}})
    cost = load(cli, config).tasks["gsm8k"].cost
    assert (cost.prompt_cost_per_1k, cost.completion_cost_per_1k) == (0.01, 0.03)
    assert cost.budget == 50.0


# "For multi-task configs, `defaults.cost` is merged into each task the same way
#  earlier checkpoints merged `prompt`, `generation`, and `evaluation`."
def test_defaults_cost_reaches_every_task(cli):
    config = multi_config("gsm8k", "mmlu", defaults={"cost": {**RATES, "budget": 50.0}})
    tasks = load(cli, config).tasks
    assert [task.cost.prompt_cost_per_1k for task in tasks.values()] == [0.01, 0.01]
    assert [task.cost.budget for task in tasks.values()] == [50.0, 50.0]


# "Per-task `cost` keys override only the keys they specify."
# "tasks:\n  code_gen:\n    cost:\n      prompt_cost_per_1k: 0.005
#   \n      completion_cost_per_1k: 0.015"
def test_per_task_cost_overrides_only_its_own_keys(cli):
    config = multi_config("gsm8k", "code_gen", defaults={"cost": {**RATES, "budget": 50.0}})
    config["tasks"]["code_gen"]["cost"] = {
        "prompt_cost_per_1k": 0.005, "completion_cost_per_1k": 0.015,
    }
    tasks = load(cli, config).tasks
    assert tasks["code_gen"].cost.prompt_cost_per_1k == 0.005
    assert tasks["code_gen"].cost.completion_cost_per_1k == 0.015
    assert tasks["code_gen"].cost.budget == 50.0
    assert tasks["gsm8k"].cost.prompt_cost_per_1k == 0.01


# "CLI flag: --budget <float>"
def test_budget_flag_overrides_config(cli):
    config = task_config(cost={**RATES, "budget": 50.0})
    assert load(cli, config, budget=2.5).only.cost.budget == 2.5


# "CLI flag: --budget <float>" - it also turns cost tracking on by itself
def test_budget_flag_without_a_cost_section(cli):
    assert load(cli, task_config(), budget=1.0).only.cost.budget == 1.0


# "prompt_cost_per_1k: 0.01" must be a usable number
def test_cost_rates_must_be_numbers(cli):
    with pytest.raises(ConfigError, match="prompt_cost_per_1k"):
        load(cli, task_config(cost={"prompt_cost_per_1k": "cheap"}))


# "Cost per API call: (prompt_tokens / 1000 * prompt_cost_per_1k) +
#  (completion_tokens / 1000 * completion_cost_per_1k)"
def test_cost_per_call_follows_the_formula(cli, api):
    run = cost_run(cli, api, numbered_rows(1))
    assert run.returncode == 0
    assert run.summary["cost"]["total"] == pytest.approx(PER_CALL)


# "track prompt cost, completion cost, and total cost"
def test_prompt_and_completion_costs_are_tracked_apart(cli, api):
    run = cost_run(cli, api, numbered_rows(4))
    cost = run.summary["cost"]
    assert cost["prompt"] == pytest.approx(4 * 0.01)
    assert cost["completion"] == pytest.approx(4 * 0.015)
    assert cost["total"] == pytest.approx(4 * PER_CALL)


# "report them to at least four decimal places"
def test_costs_keep_four_decimal_places(cli, api):
    server = api(answering(prompt_tokens=10, completion_tokens=5))
    config = task_config(api_url=server.url, rpm=600, cost=RATES)
    run = cli.run(config, numbered_rows(1))
    # 10/1000 * 0.01 + 5/1000 * 0.03 = 0.00025, which two decimals would lose
    assert run.summary["cost"]["total"] == pytest.approx(0.00025, abs=1e-9)


# "track prompt cost, completion cost, and total cost across all tasks"
def test_cost_covers_every_task(cli, api):
    server = api(answering(**USAGE))
    config = multi_config(
        "gsm8k", "mmlu",
        defaults={"api_url": server.url, "rpm": 600, "cost": RATES},
    )
    config["tasks"]["gsm8k"]["generation"] = {"scheme": "greedy"}
    from tests.conftest import SPEC_ROWS

    run = cli.run_multi(config, {"gsm8k": [SPEC_ROWS["gsm8k"]] * 2,
                                 "mmlu": [SPEC_ROWS["mmlu"]] * 3})
    assert run.returncode == 0
    assert run.summary["cost"]["total"] == pytest.approx(5 * PER_CALL)


# "include judge calls"
def test_judge_calls_are_billed(cli, api):
    server = api(judge_responder("A fine answer.", "9"))
    config = multi_config(
        "review", defaults={"api_url": server.url, "rpm": 600, "cost": RATES},
    )
    run = cli.run_multi(config, {"review": [{"prompt_text": "Describe the sea.",
                                             "criteria": "vividness"}]})
    assert run.returncode == 0
    assert run.summary["total_api_calls"] == 2
    # a generation call plus a judge call, both billed
    single = 10 / 1000 * 0.01 + 5 / 1000 * 0.03
    assert run.summary["cost"]["total"] == pytest.approx(2 * single, abs=1e-9)


# "include ... every agentic iteration"
def test_every_agentic_iteration_is_billed(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", "#### 1250000"))
    config = agentic_config(api_url=server.url, cost=RATES)
    run = cli.run(config, [{"question": "revenue?", "answer": "1250000"}])
    assert run.returncode == 0
    assert run.summary["total_api_calls"] == 2
    single = 10 / 1000 * 0.01 + 5 / 1000 * 0.03
    assert run.summary["cost"]["total"] == pytest.approx(2 * single, abs=1e-9)


# "if no cost configuration is present, omit the `cost` field from the summary"
def test_summary_omits_cost_without_configuration(cli, api):
    server = api(answering())
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(2))
    assert run.returncode == 0
    assert "cost" not in run.summary


# Summary shape: '{"cost": {"total", "prompt", "completion", "budget",
#  "budget_remaining", "budget_exceeded"}}'
def test_cost_summary_shape(cli, api):
    run = cost_run(cli, api, numbered_rows(2), budget=50.0)
    assert set(run.summary["cost"]) == {
        "total", "prompt", "completion", "budget", "budget_remaining", "budget_exceeded",
    }


# '"budget": 50.0, "budget_remaining": 37.55, "budget_exceeded": false'
def test_budget_remaining_is_reported(cli, api):
    run = cost_run(cli, api, numbered_rows(2), budget=50.0)
    cost = run.summary["cost"]
    assert cost["budget"] == 50.0
    assert cost["budget_remaining"] == pytest.approx(50.0 - 2 * PER_CALL)
    assert cost["budget_exceeded"] is False
