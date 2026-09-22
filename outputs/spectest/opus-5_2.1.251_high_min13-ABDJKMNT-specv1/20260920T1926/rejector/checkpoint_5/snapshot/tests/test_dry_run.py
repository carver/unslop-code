"""`--dry-run`: validating and estimating a run without calling the API."""

from __future__ import annotations

import pytest

from conftest import base_defaults, base_task, math_task
from fake_api import FakeAPI, always

RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
# Four rows whose rendered prompt is exactly three words each.
ROWS = [{"question": f"add {i} please", "answer": "5"} for i in range(4)]


def plain_task(api_url: str, **overrides) -> dict:
    """The base task with a system-less prompt, so word counts are predictable."""
    task = base_task(api_url, **overrides)
    task["prompt"] = {"user": "{question}"}
    return task


# Spec: "validate config and inputs, but make no API calls".
# Context: Dry Run / Rules.
def test_dry_run_makes_no_api_calls(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(plain_task(api.url))
        data = write_input(ROWS)
        result = run_cli(config, data, "--dry-run")
        assert api.call_count == 0
    assert result.returncode == 0


# Spec: "validate config and inputs" — a bad input row is still an error.
# Context: Dry Run / Rules.
def test_dry_run_still_validates_inputs(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(plain_task(api.url))
        data = write_input([{"not_question": "x"}])
        result = run_cli(config, data, "--dry-run")
    assert result.returncode == 1


# Spec: "count input rows per task" and "print the estimate JSON to stdout and
# exit 0".
# Context: Dry Run / Rules.
def test_dry_run_counts_rows_per_task(write_yaml, write_inputs, run_args, workdir):
    document = {
        "defaults": {**base_defaults("http://localhost:8000"), "cost": RATES},
        "tasks": {"a": math_task(), "b": math_task()},
    }
    config = write_yaml(document)
    data = write_inputs({"a": ROWS, "b": ROWS[:2]})
    result = run_args(
        "run", "--config", str(config), "--input-dir", str(data),
        "--output", str(workdir / "results"), "--dry-run",
    )
    assert result.returncode == 0
    assert result.summary["tasks"]["a"]["inputs"] == 4
    assert result.summary["tasks"]["b"]["inputs"] == 2
    assert result.summary["total_inputs"] == 6


# Spec: "estimate prompt tokens as average prompt word count * 1.33".
# Context: Dry Run / Rules.
def test_prompt_token_estimate(write_config, write_input, run_cli):
    config = write_config(plain_task("http://localhost:8000"))
    data = write_input(ROWS)
    result = run_cli(config, data, "--dry-run")
    assert result.summary["tasks"]["gsm8k_solve"]["est_prompt_tokens"] == round(4 * 3 * 1.33)


# Spec: "estimate total tokens as estimated prompt tokens plus max_tokens".
# Context: Dry Run / Rules.
def test_total_token_estimate(write_config, write_input, run_cli):
    config = write_config(plain_task("http://localhost:8000"))
    data = write_input(ROWS)
    result = run_cli(config, data, "--dry-run")
    task = result.summary["tasks"]["gsm8k_solve"]
    assert task["est_completion_tokens"] == 4 * 512
    assert task["est_total_tokens"] == task["est_prompt_tokens"] + task["est_completion_tokens"]
    assert result.summary["est_total_tokens"] == task["est_total_tokens"]


# Spec: "estimate cost using the configured cost rates".
# Context: Dry Run / Rules.
def test_cost_estimate_uses_the_configured_rates(write_config, write_input, run_cli):
    config = write_config(plain_task("http://localhost:8000", cost=RATES))
    data = write_input(ROWS)
    result = run_cli(config, data, "--dry-run")
    task = result.summary["tasks"]["gsm8k_solve"]
    expected = task["est_prompt_tokens"] / 1000 * 0.01 + task["est_completion_tokens"] / 1000 * 0.03
    assert task["est_cost"] == pytest.approx(expected, abs=1e-6)
    assert result.summary["est_total_cost"] == pytest.approx(expected, abs=1e-6)


# Spec: "estimate time in minutes as total_inputs * avg_attempts / rpm, where
# avg_attempts is 1 for greedy and sample".
# Context: Dry Run / Rules.
def test_time_estimate_for_greedy(write_config, write_input, run_cli):
    config = write_config(plain_task("http://localhost:8000"))
    data = write_input(ROWS)
    result = run_cli(config, data, "--dry-run")
    assert result.summary["est_time_minutes"] == pytest.approx(4 * 1 / 600, abs=1e-9)


# Spec: "avg_attempts is ... n for rejection worst-case planning; prefer
# precision over rounding".
# Context: Dry Run / Rules.
def test_time_estimate_for_rejection(write_config, write_input, run_cli):
    task = plain_task("http://localhost:8000")
    task["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 5, "max_tokens": 512}
    task["rpm"] = 7
    config = write_config(task)
    data = write_input(ROWS)
    result = run_cli(config, data, "--dry-run")
    assert result.summary["est_time_minutes"] == pytest.approx(4 * 5 / 7, abs=1e-9)


# Spec: the estimate JSON's key set.
# Context: Dry Run / Example.
def test_estimate_shape(write_config, write_input, run_cli):
    config = write_config(plain_task("http://localhost:8000", cost=RATES))
    data = write_input(ROWS)
    result = run_cli(config, data, "--dry-run")
    assert set(result.summary) == {
        "tasks",
        "total_inputs",
        "est_total_tokens",
        "est_total_cost",
        "est_time_minutes",
    }
    assert set(result.summary["tasks"]["gsm8k_solve"]) == {
        "inputs",
        "est_prompt_tokens",
        "est_completion_tokens",
        "est_total_tokens",
        "est_cost",
    }


# Spec: "print the estimate JSON to stdout and exit 0" — no output file is
# written, since nothing ran.
# Context: Dry Run / Rules.
def test_dry_run_writes_no_output_file(write_config, write_input, run_cli):
    config = write_config(plain_task("http://localhost:8000"))
    data = write_input(ROWS)
    result = run_cli(config, data, "--dry-run")
    assert not result.output_path.exists()
