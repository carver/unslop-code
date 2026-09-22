"""Cost accounting, the `cost` summary block, and budget exhaustion."""

from __future__ import annotations

from fake_server import FakeAPIServer, Reply, completion, system_of
from conftest import GSM8K_TASK, MMLU_TASK, base_config, multi_config

from rejector_core.config import load_config

RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
# One call at these rates costs 10000/1000*0.01 + 20000/1000*0.03 = 0.70.
USAGE = {"prompt_tokens": 10000, "completion_tokens": 20000}
CALL_COST = 0.70


def _rows(write_input, count=1):
    return write_input([{"question": f"q{i}", "answer": "5"} for i in range(count)])


def _priced(**usage):
    body = completion("#### 5", **{**USAGE, **usage})
    return lambda payload, index: Reply(body)


# Spec: "defaults.cost is merged into each task the same way earlier
# checkpoints merged prompt, generation, and evaluation"
def test_defaults_cost_reaches_every_task(write_config):
    config_map = multi_config("http://x", {"gsm8k": GSM8K_TASK, "mmlu": MMLU_TASK})
    config_map["defaults"]["cost"] = {**RATES, "budget": 50.0}
    tasks = load_config(write_config(config_map), {}).tasks

    assert [task.cost.budget for task in tasks] == [50.0, 50.0]
    assert [task.cost.prompt_cost_per_1k for task in tasks] == [0.01, 0.01]


# Spec: "Per-task `cost` keys override only the keys they specify."
def test_per_task_cost_overrides_only_its_own_keys(write_config):
    code_gen = dict(GSM8K_TASK, cost={"prompt_cost_per_1k": 0.005})
    config_map = multi_config("http://x", {"code_gen": code_gen, "mmlu": MMLU_TASK})
    config_map["defaults"]["cost"] = {**RATES, "budget": 50.0}
    tasks = {task.name: task for task in load_config(write_config(config_map), {}).tasks}

    assert tasks["code_gen"].cost.prompt_cost_per_1k == 0.005
    assert tasks["code_gen"].cost.completion_cost_per_1k == 0.03
    assert tasks["code_gen"].cost.budget == 50.0


# Spec: CLI flag "--budget <float>"
def test_budget_flag_overrides_the_config(write_config):
    config_map = base_config("http://x", cost={**RATES, "budget": 50.0})
    task = load_config(write_config(config_map), {"budget": 2.5}).tasks[0]
    assert task.cost.budget == 2.5


# Spec: cost per call is
# "(prompt_tokens / 1000 * prompt_cost_per_1k) +
#  (completion_tokens / 1000 * completion_cost_per_1k)"
def test_cost_totals_follow_the_per_call_formula(write_config, write_input, run_cli):
    with FakeAPIServer(_priced()) as api:
        config = write_config(base_config(api.url, cost=RATES))
        result = run_cli(config, _rows(write_input, 3))

    cost = result.summary["cost"]
    assert cost["prompt"] == round(3 * 10000 / 1000 * 0.01, 2)
    assert cost["completion"] == round(3 * 20000 / 1000 * 0.03, 2)
    assert cost["total"] == round(3 * CALL_COST, 2)


# Spec: "if no cost configuration is present, omit the `cost` field from the
# summary"
def test_summary_omits_cost_without_configuration(write_config, write_input, run_cli):
    with FakeAPIServer(_priced()) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, _rows(write_input))

    assert "cost" not in result.summary


# Spec: "include judge calls and every agentic iteration"
def test_judge_calls_are_charged(write_config, write_input, run_cli):
    def responder(payload, index):
        text = "5" if "Score" in system_of(payload) else "#### 5"
        return Reply(completion(text, **USAGE))

    with FakeAPIServer(responder) as api:
        config_map = base_config(api.url, cost=RATES)
        config_map["task"]["evaluation"] = {
            "type": "llm_judge",
            "threshold": 4,
            "judge_prompt": {"system": "Score it", "user": "{question}"},
        }
        result = run_cli(write_config(config_map), _rows(write_input, 2))

    assert result.summary["cost"]["total"] == round(4 * CALL_COST, 2)


# Spec: "include judge calls and every agentic iteration"
def test_every_agentic_iteration_is_charged(write_config, write_input, run_cli):
    from conftest import agentic_config
    from fake_server import conversation

    responder = conversation([[("lookup", {"key": "employees"})], "#### 142"], **USAGE)
    with FakeAPIServer(responder) as api:
        config_map = agentic_config(api.url, cost=RATES)
        result = run_cli(write_config(config_map), _rows(write_input, 2))

    assert result.summary["cost"]["total"] == round(4 * CALL_COST, 2)


# Spec: the `cost` summary shape carries budget, budget_remaining and
# budget_exceeded alongside the totals
def test_cost_block_reports_the_budget_and_what_is_left(write_config, write_input, run_cli):
    with FakeAPIServer(_priced()) as api:
        config = write_config(base_config(api.url, cost={**RATES, "budget": 50.0}))
        result = run_cli(config, _rows(write_input, 2))

    assert result.summary["cost"] == {
        "total": round(2 * CALL_COST, 2),
        "prompt": round(2 * 10000 / 1000 * 0.01, 2),
        "completion": round(2 * 20000 / 1000 * 0.03, 2),
        "budget": 50.0,
        "budget_remaining": round(50.0 - 2 * CALL_COST, 2),
        "budget_exceeded": False,
    }


# Spec: "when `budget` is configured and the running total reaches or exceeds
# it: stop sending new requests immediately ... and exit `0`"
def test_budget_exhaustion_exits_zero_and_reports_the_flag(write_config, write_input, run_cli):
    with FakeAPIServer(_priced()) as api:
        config_map = base_config(api.url, rate_limits={"max_concurrent": 1}, cost={**RATES, "budget": 1.0})
        result = run_cli(write_config(config_map), _rows(write_input, 10))
        calls = len(api.requests)

    assert result.returncode == 0
    assert result.summary["cost"]["budget_exceeded"] is True
    assert calls < 10


# Spec: "budget exhaustion is not an error; partial output is valid" - only
# the rows that actually ran are written (T88)
def test_budget_exhaustion_writes_only_completed_rows(write_config, write_input, run_cli):
    with FakeAPIServer(_priced()) as api:
        config_map = base_config(api.url, rate_limits={"max_concurrent": 1}, cost={**RATES, "budget": 1.0})
        result = run_cli(write_config(config_map), _rows(write_input, 10))

    assert 0 < len(result.rows) < 10
    assert result.summary["total"] == len(result.rows)


# Spec: "budget_remaining" never goes below zero once the budget is spent
def test_budget_remaining_is_clamped_at_zero(write_config, write_input, run_cli):
    with FakeAPIServer(_priced()) as api:
        config_map = base_config(api.url, rate_limits={"max_concurrent": 1}, cost={**RATES, "budget": 1.0})
        result = run_cli(write_config(config_map), _rows(write_input, 10))

    assert result.summary["cost"]["budget_remaining"] == 0.0


# Spec: "track prompt cost, completion cost, and total cost across all tasks"
def test_cost_is_aggregated_across_tasks(write_config, write_input, run_argv):
    def responder(payload, index):
        return Reply(completion("#### 5" if "math" in system_of(payload) else "B", **USAGE))

    with FakeAPIServer(responder) as api:
        config_map = multi_config(api.url, {"gsm8k": GSM8K_TASK, "mmlu": MMLU_TASK})
        config_map["defaults"]["cost"] = RATES
        config = write_config(config_map)
        gsm8k = write_input([{"question": "q", "answer": "5"}], name="gsm8k.jsonl")
        mmlu = write_input(
            [{"question": "q", "a": "1", "b": "2", "c": "3", "d": "4", "answer": "B"}],
            name="mmlu.jsonl",
        )
        result = run_argv("--config", config, "--input", f"gsm8k={gsm8k}", "--input", f"mmlu={mmlu}")

    assert result.summary["cost"]["total"] == round(2 * CALL_COST, 2)


# Spec: "if no cost configuration is present" - rates alone still produce a
# cost block, with a null budget (T90)
def test_rates_without_a_budget_report_a_null_budget(write_config, write_input, run_cli):
    with FakeAPIServer(_priced()) as api:
        config = write_config(base_config(api.url, cost=RATES))
        result = run_cli(config, _rows(write_input))

    assert result.summary["cost"]["budget"] is None
    assert result.summary["cost"]["budget_remaining"] is None
    assert result.summary["cost"]["budget_exceeded"] is False
