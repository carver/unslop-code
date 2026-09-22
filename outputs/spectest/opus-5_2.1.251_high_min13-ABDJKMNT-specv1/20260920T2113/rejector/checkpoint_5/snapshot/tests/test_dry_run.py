"""`--dry-run`: the estimate printed instead of calling the API."""

from __future__ import annotations

import json

import pytest

from tests.conftest import answering, multi_config, task_config

#: A task whose rendered request is exactly the question, five words below.
NO_SYSTEM = {"system": None, "user": "{question}"}
FIVE_WORDS = "one two three four five"
RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
#: average prompt word count * 1.33, for three five-word rows
PROMPT_TOKENS = 5 * 1.33 * 3


def rows(count: int = 3) -> list[dict]:
    return [{"question": FIVE_WORDS, "answer": "5"} for _ in range(count)]


def dry_config(server, **overrides):
    return task_config(api_url=server.url, rpm=60, prompt=NO_SYSTEM,
                       generation={"scheme": "greedy", "max_tokens": 100}, **overrides)


def estimate(run) -> dict:
    return json.loads(run.stdout.strip().splitlines()[-1])


# "validate config and inputs, but make no API calls" / "exit `0`"
def test_dry_run_makes_no_api_calls(cli, api):
    server = api(answering())
    run = cli.run(dry_config(server), rows(), "--dry-run")
    assert run.returncode == 0
    assert server.log.calls == []


# "print the estimate JSON to stdout and exit `0`" - and write no output file
def test_dry_run_writes_no_output_file(cli, api):
    server = api(answering())
    run = cli.run(dry_config(server), rows(), "--dry-run")
    assert not run.output_path.exists()
    assert set(estimate(run)) == {
        "tasks", "total_inputs", "est_total_tokens", "est_total_cost", "est_time_minutes",
    }


# '"tasks": {"gsm8k": {"inputs": 1000, "est_prompt_tokens": ..., ...}}'
def test_task_entry_shape(cli, api):
    server = api(answering())
    run = cli.run(dry_config(server), rows(), "--dry-run")
    task = estimate(run)["tasks"]["math_solve"]
    assert set(task) == {
        "inputs", "est_prompt_tokens", "est_completion_tokens", "est_total_tokens",
        "est_cost",
    }


# "count input rows per task"
def test_input_rows_are_counted(cli, api):
    server = api(answering())
    run = cli.run(dry_config(server), rows(7), "--dry-run")
    assert estimate(run)["tasks"]["math_solve"]["inputs"] == 7
    assert estimate(run)["total_inputs"] == 7


# "estimate prompt tokens as `average prompt word count * 1.33`"
def test_prompt_tokens_scale_the_average_word_count(cli, api):
    server = api(answering())
    run = cli.run(dry_config(server), rows(), "--dry-run")
    assert estimate(run)["tasks"]["math_solve"]["est_prompt_tokens"] == round(PROMPT_TOKENS)


# "estimate prompt tokens as `average prompt word count * 1.33`" - the average is
# taken over rows of differing length
def test_prompt_tokens_use_the_average_over_rows(cli, api):
    server = api(answering())
    mixed = [{"question": "one", "answer": "5"}, {"question": "one two three", "answer": "5"}]
    run = cli.run(dry_config(server), mixed, "--dry-run")
    assert estimate(run)["tasks"]["math_solve"]["est_prompt_tokens"] == round(2 * 1.33 * 2)


# "estimate total tokens as estimated prompt tokens plus `max_tokens`"
def test_total_tokens_add_the_completion_budget(cli, api):
    server = api(answering())
    task = estimate(cli.run(dry_config(server), rows(), "--dry-run"))["tasks"]["math_solve"]
    assert task["est_completion_tokens"] == 3 * 100
    assert task["est_total_tokens"] == task["est_prompt_tokens"] + task["est_completion_tokens"]


# "estimate cost using the configured cost rates"
def test_cost_uses_the_configured_rates(cli, api):
    server = api(answering())
    run = cli.run(dry_config(server, cost=RATES), rows(), "--dry-run")
    expected = PROMPT_TOKENS / 1000 * 0.01 + 300 / 1000 * 0.03
    assert estimate(run)["tasks"]["math_solve"]["est_cost"] == pytest.approx(expected, abs=1e-6)
    assert estimate(run)["est_total_cost"] == pytest.approx(expected, abs=1e-6)


# "estimate time in minutes as `total_inputs * avg_attempts / rpm`, where
#  `avg_attempts` is `1` for `greedy` and `sample`"
@pytest.mark.parametrize("generation", [
    {"scheme": "greedy", "max_tokens": 100},
    {"scheme": "sample", "temperature": 0.7, "max_tokens": 100},
])
def test_time_estimate_for_one_attempt_per_row(cli, api, generation):
    server = api(answering())
    config = task_config(api_url=server.url, rpm=60, prompt=NO_SYSTEM,
                         generation=generation)
    run = cli.run(config, rows(30), "--dry-run")
    assert estimate(run)["est_time_minutes"] == pytest.approx(30 * 1 / 60)


# "`avg_attempts` is ... `n` for rejection worst-case planning; prefer precision
#  over rounding"
def test_time_estimate_for_rejection_uses_the_attempt_budget(cli, api):
    server = api(answering())
    config = task_config(
        api_url=server.url, rpm=60, prompt=NO_SYSTEM,
        generation={"scheme": "rejection", "temperature": 0.7, "n": 5, "max_tokens": 100},
    )
    run = cli.run(config, rows(7), "--dry-run")
    assert estimate(run)["est_time_minutes"] == pytest.approx(7 * 5 / 60)


# "validate config and inputs, but make no API calls" - a bad config still fails
def test_dry_run_validates_the_config(cli, api):
    server = api(answering())
    config = dry_config(server)
    config["task"].pop("model")
    run = cli.run(config, rows(), "--dry-run")
    assert run.returncode == 1
    assert "model" in run.stderr


# "validate config and inputs, but make no API calls" - so do bad inputs
def test_dry_run_validates_the_inputs(cli, api):
    server = api(answering())
    run = cli.run(dry_config(server), [{"answer": "5"}], "--dry-run")
    assert run.returncode == 1
    assert "question" in run.stderr


# "count input rows per task" / '"total_inputs": 1000' - a multi-task config
# reports every task and the run totals
def test_multi_task_estimate_totals(cli, api):
    from tests.conftest import SPEC_ROWS

    server = api(answering())
    config = multi_config("gsm8k", "mmlu",
                          defaults={"api_url": server.url, "rpm": 60, "cost": RATES})
    run = cli.run_multi(
        config, {"gsm8k": [SPEC_ROWS["gsm8k"]] * 4, "mmlu": [SPEC_ROWS["mmlu"]] * 2},
        "--dry-run",
    )
    report = estimate(run)
    assert set(report["tasks"]) == {"gsm8k", "mmlu"}
    assert report["total_inputs"] == 6
    assert report["est_total_tokens"] == sum(
        task["est_total_tokens"] for task in report["tasks"].values()
    )
    # the run total is rounded on its own, so it may differ from the rounded
    # per-task entries in the last place
    assert report["est_total_cost"] == pytest.approx(
        sum(task["est_cost"] for task in report["tasks"].values()), abs=1e-5
    )
    # gsm8k is rejection with n: 5, mmlu is greedy
    assert report["est_time_minutes"] == pytest.approx((4 * 5 + 2 * 1) / 60)
