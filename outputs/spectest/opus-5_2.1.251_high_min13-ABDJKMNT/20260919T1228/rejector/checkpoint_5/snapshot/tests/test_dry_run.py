"""`--dry-run`: validate everything, estimate the run, call no API."""

from __future__ import annotations

import json

from conftest import exact_match_task, make_config, make_multi_config

ROWS = [{"question": f"q{index}", "answer": "1"} for index in range(4)]
RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
# "Solve it." plus a one-word question is three words per row.
WORDS_PER_ROW = 3


def dry_config(server_url, **overrides):
    return make_config(
        server_url,
        prompt={"system": "Solve it.", "user": "{question}"},
        rate_limits={"rpm": 8},
        cost=dict(RATES),
        **overrides,
    )


def estimate(result) -> dict:
    return json.loads(result.stdout)


# Spec: "validate config and inputs, but make no API calls" and "print the
# estimate JSON to stdout and exit `0`".
def test_dry_run_makes_no_api_calls(server, run_cli):
    result = run_cli(dry_config(server.url), ROWS, "--dry-run")
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 0
    assert isinstance(estimate(result), dict)
    assert not result.output_path.exists()


# Spec: "count input rows per task", "estimate prompt tokens as `average prompt
# word count * 1.33`", "estimate total tokens as estimated prompt tokens plus
# `max_tokens`", "estimate cost using the configured cost rates".
def test_estimate_numbers(server, run_cli):
    result = run_cli(dry_config(server.url), ROWS, "--dry-run")
    task = estimate(result)["tasks"]["gsm8k_solve"]
    assert task["inputs"] == 4
    assert task["est_prompt_tokens"] == round(4 * WORDS_PER_ROW * 1.33)
    assert task["est_completion_tokens"] == 4 * 512
    assert task["est_total_tokens"] == task["est_prompt_tokens"] + 4 * 512
    assert task["est_cost"] == round(16 / 1000 * 0.01 + 2048 / 1000 * 0.03, 6)


# Spec: the run-level totals of the estimate JSON.
def test_estimate_totals(server, run_cli):
    result = run_cli(dry_config(server.url), ROWS, "--dry-run")
    report = estimate(result)
    task = report["tasks"]["gsm8k_solve"]
    assert report["total_inputs"] == 4
    assert report["est_total_tokens"] == task["est_total_tokens"]
    assert report["est_total_cost"] == task["est_cost"]


# Spec: "estimate time in minutes as `total_inputs * avg_attempts / rpm`, where
# `avg_attempts` is `1` for `greedy` and `sample`".
def test_time_estimate_for_greedy(server, run_cli):
    result = run_cli(dry_config(server.url), ROWS, "--dry-run")
    assert estimate(result)["est_time_minutes"] == 0.5


# Spec: "... and `n` for rejection worst-case planning". (T103)
def test_time_estimate_for_rejection(server, run_cli):
    config = dry_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 4}
    )
    result = run_cli(config, ROWS, "--dry-run")
    assert estimate(result)["est_time_minutes"] == 2.0


# Spec: "count input rows per task" -- a multi-task run estimates each task.
def test_multi_task_estimate(server, run_multi):
    config = make_multi_config(
        server.url,
        {"gsm8k": exact_match_task(), "mmlu": exact_match_task()},
        rate_limits={"rpm": 8},
        cost=dict(RATES),
        prompt={"system": "Solve it.", "user": "{question}"},
    )
    result = run_multi(config, {"gsm8k": ROWS, "mmlu": ROWS[:2]}, "--dry-run")
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert set(report["tasks"]) == {"gsm8k", "mmlu"}
    assert report["tasks"]["mmlu"]["inputs"] == 2
    assert report["total_inputs"] == 6
    assert report["est_total_cost"] == round(
        sum(task["est_cost"] for task in report["tasks"].values()), 6
    )


# Spec: "validate config and inputs" -- a config error still exits 1.
def test_dry_run_still_validates_the_config(server, run_cli):
    config = dry_config(server.url, generation={"scheme": "beam"})
    result = run_cli(config, ROWS, "--dry-run")
    assert result.exit_code == 1
    assert "beam" in result.stderr


# Spec: "validate config and inputs" -- a row missing a template field too.
def test_dry_run_still_validates_the_input(server, run_cli):
    result = run_cli(dry_config(server.url), [{"answer": "1"}], "--dry-run")
    assert result.exit_code == 1
    assert result.stderr.strip()


# Spec: "estimate cost using the configured cost rates" -- with no rates
# configured there is nothing to charge.
def test_estimate_without_cost_config(server, run_cli):
    config = make_config(
        server.url,
        prompt={"system": "Solve it.", "user": "{question}"},
        rate_limits={"rpm": 8},
    )
    result = run_cli(config, ROWS, "--dry-run")
    assert result.exit_code == 0, result.stderr
    assert estimate(result)["est_total_cost"] == 0.0
