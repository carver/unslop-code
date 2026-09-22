"""Where `rate_limits` and `cost` come from: defaults, per-task, CLI flags."""

from __future__ import annotations

import json

from conftest import exact_match_task, make_config, make_multi_config

ROWS = [{"question": f"q{index}", "answer": "1"} for index in range(4)]
MULTI_ROWS = {"gsm8k": ROWS, "mmlu": ROWS}


def estimate(result) -> dict:
    return json.loads(result.stdout)


# Spec: "For multi-task configs, `defaults.rate_limits` is merged into each
# task the same way earlier checkpoints merged `prompt`, `generation`, and
# `evaluation`" -- the dry-run time estimate is paced by the inherited rpm.
def test_defaults_rate_limits_reach_every_task(server, run_multi):
    config = make_multi_config(
        server.url,
        {"gsm8k": exact_match_task(), "mmlu": exact_match_task()},
        rate_limits={"rpm": 8},
    )
    result = run_multi(config, MULTI_ROWS, "--dry-run")
    assert result.exit_code == 0, result.stderr
    # Two tasks of four greedy rows each, one attempt apiece, at 8 rpm.
    assert estimate(result)["est_time_minutes"] == 1.0


# Spec: "Per-task `rate_limits` keys override only the keys they specify."
def test_task_rate_limits_override_one_key_only(server, run_multi):
    config = make_multi_config(
        server.url,
        {
            "gsm8k": exact_match_task(rate_limits={"tpm": 30000}),
            "mmlu": exact_match_task(rate_limits={"rpm": 2}),
        },
        rate_limits={"rpm": 8, "tpm": 50000, "max_concurrent": 10},
    )
    result = run_multi(config, MULTI_ROWS, "--dry-run")
    assert result.exit_code == 0, result.stderr
    # gsm8k keeps the inherited 8 rpm (0.5 min); mmlu overrides it with 2 (2.0).
    assert estimate(result)["est_time_minutes"] == 2.5


# Spec: "Per-task override: tasks: code_gen: rate_limits: tpm: 30000" -- a
# single-task config reads the same block.
def test_single_task_rate_limits_are_honoured(server, run_cli):
    config = make_config(server.url, rate_limits={"max_concurrent": 2}, rpm=None)
    result = run_cli(config, ROWS, "--dry-run")
    assert result.exit_code == 0, result.stderr
    assert estimate(result)["tasks"]["gsm8k_solve"]["inputs"] == 4


# Spec: "`--max-concurrent <int>`" overrides the configured cap.
def test_max_concurrent_flag_overrides_the_config(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.1, workers=8)
    config = make_config(server.url, rate_limits={"max_concurrent": 8})
    result = run_cli(config, ROWS, "--max-concurrent", "1")
    assert result.exit_code == 0, result.stderr
    assert server.peak_concurrency == 1


# Spec: "`--tpm <int>`" overrides the configured token budget. Each request
# reserves 512 max_tokens plus its prompt estimate, so an 800-token minute has
# room for one at a time -- but for a second once the first records its much
# smaller actual usage.
def test_tpm_flag_overrides_the_config(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.1, workers=8)
    config = make_config(server.url, rate_limits={"tpm": 500000})
    rows = ROWS[:2]
    result = run_cli(config, rows, "--tpm", "800", "--max-tokens", "512")
    assert result.exit_code == 0, result.stderr
    assert len(result.rows) == 2
    assert server.peak_concurrency == 1


# Spec: "if `rpm` is omitted, RPM limiting is disabled for that task" -- more
# requests than any Part 1 default would have allowed still go out at once.
def test_rpm_omitted_leaves_requests_unpaced(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.1, workers=16)
    config = make_config(server.url, rpm=None)
    rows = [{"question": f"q{i}", "answer": "1"} for i in range(12)]
    result = run_cli(config, rows)
    assert result.exit_code == 0, result.stderr
    assert server.peak_concurrency >= 8
    assert result.summary["elapsed_seconds"] < 3.0


# Spec: "For multi-task configs, `defaults.cost` is merged into each task the
# same way earlier checkpoints merged `prompt`, `generation`, and `evaluation`."
def test_defaults_cost_reaches_every_task(servers, run_multi):
    server = servers(prompt_tokens=1000, completion_tokens=1000)
    config = make_multi_config(
        server.url,
        {"gsm8k": exact_match_task(), "mmlu": exact_match_task()},
        cost={"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03},
    )
    result = run_multi(config, MULTI_ROWS)
    assert result.exit_code == 0, result.stderr
    # Eight calls across the two tasks, each costing 0.01 + 0.03.
    assert result.summary["cost"]["total"] == 0.32


# Spec: "Per-task `cost` keys override only the keys they specify."
def test_task_cost_keys_override_one_key_only(servers, run_multi):
    server = servers(prompt_tokens=1000, completion_tokens=1000)
    config = make_multi_config(
        server.url,
        {
            "gsm8k": exact_match_task(cost={"prompt_cost_per_1k": 0.005}),
            "mmlu": exact_match_task(),
        },
        cost={"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03},
    )
    result = run_multi(config, MULTI_ROWS)
    assert result.exit_code == 0, result.stderr
    # gsm8k: 4 * (0.005 + 0.03); mmlu: 4 * (0.01 + 0.03).
    assert result.summary["cost"]["prompt"] == 0.06
    assert result.summary["cost"]["total"] == 0.3


# Spec: "`--budget <float>`" overrides the configured budget.
def test_budget_flag_overrides_the_config(servers, run_cli):
    server = servers(prompt_tokens=1000, completion_tokens=1000)
    config = make_config(
        server.url,
        cost={
            "prompt_cost_per_1k": 0.01,
            "completion_cost_per_1k": 0.03,
            "budget": 100.0,
        },
    )
    result = run_cli(config, ROWS, "--budget", "0.05")
    assert result.exit_code == 0, result.stderr
    assert result.summary["cost"]["budget"] == 0.05
    assert result.summary["cost"]["budget_exceeded"] is True
