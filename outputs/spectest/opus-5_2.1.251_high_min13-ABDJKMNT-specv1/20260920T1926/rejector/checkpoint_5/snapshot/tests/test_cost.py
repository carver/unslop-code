"""Cost accounting, the run budget, and the summary's `cost` object."""

from __future__ import annotations

from conftest import agentic_task, base_defaults, base_task, judge_task, math_task
from fake_api import FakeAPI, Reply, always, by_system, call, turns
from taskrunner.config import build_run_config

RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}


def costed_task(api_url: str, **cost) -> dict:
    """The spec's base task with a cost block."""
    return base_task(api_url, cost={**RATES, **cost})


# Spec: "defaults: cost: {prompt_cost_per_1k, completion_cost_per_1k, budget}"
# merged "into each task the same way earlier checkpoints merged prompt,
# generation, and evaluation".
# Context: Cost Tracking / Configuration.
def test_defaults_cost_merges_into_every_task():
    document = {
        "defaults": {**base_defaults("http://localhost:8000"), "cost": {**RATES, "budget": 50.0}},
        "tasks": {"a": math_task(), "b": math_task()},
    }
    config = build_run_config(document, {})
    for name in ("a", "b"):
        cost = config.tasks[name].cost
        assert (cost.prompt_cost_per_1k, cost.completion_cost_per_1k, cost.budget) == (
            0.01,
            0.03,
            50.0,
        )


# Spec: "Per-task cost keys override only the keys they specify."
# Context: Cost Tracking / Per-task override.
def test_per_task_cost_overrides_single_keys():
    document = {
        "defaults": {**base_defaults("http://localhost:8000"), "cost": {**RATES, "budget": 50.0}},
        "tasks": {
            "code_gen": math_task(
                cost={"prompt_cost_per_1k": 0.005, "completion_cost_per_1k": 0.015}
            )
        },
    }
    cost = build_run_config(document, {}).tasks["code_gen"].cost
    assert (cost.prompt_cost_per_1k, cost.completion_cost_per_1k, cost.budget) == (
        0.005,
        0.015,
        50.0,
    )


# Spec: "CLI flag: --budget <float>".
# Context: Cost Tracking / CLI flag.
def test_budget_flag_overrides_config():
    task = base_task("http://localhost:8000", cost={**RATES, "budget": 5.0})
    config = build_run_config({"task": task}, {"budget": 2.5})
    assert config.tasks["gsm8k_solve"].cost.budget == 2.5


# Spec: "Cost per API call: (prompt_tokens / 1000 * prompt_cost_per_1k) +
# (completion_tokens / 1000 * completion_cost_per_1k)".
# Context: Cost Tracking.
def test_cost_per_call_uses_the_configured_rates(write_config, write_input, run_cli):
    reply = Reply(content="#### 5", prompt_tokens=2000, completion_tokens=1000)
    with FakeAPI(responder=lambda index, body: reply) as api:
        config = write_config(costed_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    cost = result.summary["cost"]
    assert cost["prompt"] == 0.02
    assert cost["completion"] == 0.03
    assert cost["total"] == 0.05


# Spec: "track prompt cost, completion cost, and total cost across all tasks".
# Context: Cost Tracking / Rules.
def test_cost_is_tracked_across_all_tasks(write_yaml, write_inputs, run_args, workdir):
    reply = Reply(content="#### 5", prompt_tokens=1000, completion_tokens=1000)
    with FakeAPI(responder=lambda index, body: reply) as api:
        document = {
            "defaults": {**base_defaults(api.url), "cost": RATES},
            "tasks": {"a": math_task(), "b": math_task()},
        }
        config = write_yaml(document)
        data = write_inputs({name: [{"question": "q", "answer": "5"}] for name in ("a", "b")})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
    assert result.summary["cost"]["total"] == 0.08


# Spec: "report them to at least four decimal places".
# Context: Cost Tracking / Rules.
def test_small_costs_keep_four_decimal_places(write_config, write_input, run_cli):
    reply = Reply(content="#### 5", prompt_tokens=10, completion_tokens=10)
    with FakeAPI(responder=lambda index, body: reply) as api:
        config = write_config(costed_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    # 10/1000*0.01 = 0.0001 and 10/1000*0.03 = 0.0003.
    assert result.summary["cost"]["prompt"] == 0.0001
    assert result.summary["cost"]["completion"] == 0.0003


# Spec: "include judge calls and every agentic iteration".
# Context: Cost Tracking / Rules.
def test_judge_calls_are_costed(write_config, write_input, run_cli):
    replies = {
        "You are a writing assistant.": Reply(
            content="a draft", prompt_tokens=1000, completion_tokens=1000
        ),
        "You are a quality evaluator.": Reply(
            content="9", prompt_tokens=1000, completion_tokens=1000
        ),
    }
    with FakeAPI(responder=by_system(replies)) as api:
        task = judge_task(name="j", api_url=api.url, model="gpt-4", rpm=600, cost=RATES)
        config = write_config(task)
        data = write_input([{"prompt_text": "p", "criteria": "clear"}])
        result = run_cli(config, data)
    assert result.summary["cost"]["total"] == 0.08


# Spec: "include judge calls and every agentic iteration".
# Context: Cost Tracking / Rules.
def test_every_agentic_iteration_is_costed(write_config, write_input, run_cli):
    script = [
        Reply(
            content=None,
            tools=(call("lookup", key="employees"),),
            prompt_tokens=1000,
            completion_tokens=1000,
        ),
        Reply(content="#### 142", prompt_tokens=1000, completion_tokens=1000),
    ]
    with FakeAPI(responder=turns(script)) as api:
        config = write_config(agentic_task(api.url, cost=RATES))
        data = write_input([{"question": "q", "answer": "142"}])
        result = run_cli(config, data)
    assert result.summary["cost"]["total"] == 0.08


# Spec: "when budget is configured and the running total reaches or exceeds
# it: stop sending new requests immediately, let in-flight requests finish,
# write completed results, print the summary, and exit 0".
# Context: Cost Tracking / Rules; each call costs $0.04, so a $0.10 budget is
# reached partway through twenty rows.
def test_budget_exhaustion_stops_the_run_and_exits_zero(write_config, write_input, run_cli):
    reply = Reply(content="#### 5", prompt_tokens=1000, completion_tokens=1000)
    with FakeAPI(responder=lambda index, body: reply, slots=2, delay=0.05) as api:
        task = costed_task(api.url, budget=0.10)
        task["rate_limits"] = {"max_concurrent": 2}
        config = write_config(task)
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(20)])
        result = run_cli(config, data)
    assert result.returncode == 0
    assert result.summary["cost"]["budget_exceeded"] is True
    assert result.summary["cost"]["total"] >= 0.10
    assert 0 < len(result.rows) < 20


# Spec: "budget exhaustion is not an error; partial output is valid."
# Context: Cost Tracking / Rules; the rows that did run are complete rows.
def test_partial_output_is_valid(write_config, write_input, run_cli):
    reply = Reply(content="#### 5", prompt_tokens=1000, completion_tokens=1000)
    with FakeAPI(responder=lambda index, body: reply, slots=2, delay=0.05) as api:
        task = costed_task(api.url, budget=0.10)
        task["rate_limits"] = {"max_concurrent": 2}
        config = write_config(task)
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(20)])
        result = run_cli(config, data)
    for index, row in enumerate(result.rows):
        assert row["input"]["question"] == f"q{index}"
        assert row["result"]["passed"] is True
    assert result.summary["total"] == len(result.rows)


# Spec: the `cost` summary shape with total, prompt, completion, budget,
# budget_remaining and budget_exceeded.
# Context: Cost Tracking / Summary shape.
def test_cost_summary_shape(write_config, write_input, run_cli):
    reply = Reply(content="#### 5", prompt_tokens=1000, completion_tokens=1000)
    with FakeAPI(responder=lambda index, body: reply) as api:
        config = write_config(costed_task(api.url, budget=50.0))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    cost = result.summary["cost"]
    assert set(cost) == {
        "total",
        "prompt",
        "completion",
        "budget",
        "budget_remaining",
        "budget_exceeded",
    }
    assert cost["budget"] == 50.0
    assert cost["budget_remaining"] == 50.0 - cost["total"]
    assert cost["budget_exceeded"] is False


# Spec: "if no cost configuration is present, omit the cost field from the
# summary".
# Context: Cost Tracking / Rules.
def test_cost_field_omitted_without_cost_configuration(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    assert "cost" not in result.summary


# Spec: "if budget: 1.00 and the running total reaches $1.02 ... print
# cost.budget_exceeded: true ... exit 0".
# Context: Examples / Budget exceeded.
def test_budget_exceeded_example(write_config, write_input, run_cli):
    # Each call costs 0.51: 1000 prompt tokens at 0.06 plus 1000 completion
    # tokens at 0.45, so two calls overshoot a $1.00 budget to $1.02.
    reply = Reply(content="#### 5", prompt_tokens=1000, completion_tokens=1000)
    with FakeAPI(responder=lambda index, body: reply, slots=1, delay=0.05) as api:
        task = base_task(
            api.url,
            cost={"prompt_cost_per_1k": 0.06, "completion_cost_per_1k": 0.45, "budget": 1.00},
            rate_limits={"max_concurrent": 1},
        )
        config = write_config(task)
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(10)])
        result = run_cli(config, data)
    assert result.returncode == 0
    assert result.summary["cost"]["total"] == 1.02
    assert result.summary["cost"]["budget_exceeded"] is True
    assert result.summary["cost"]["budget_remaining"] == -0.02
    assert len(result.rows) == 2
