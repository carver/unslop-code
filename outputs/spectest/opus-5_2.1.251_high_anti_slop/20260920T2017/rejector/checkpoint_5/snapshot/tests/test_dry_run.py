"""The `--dry-run` estimate, which validates the run without sending anything."""

import json

import yaml
from conftest import run_cli, write_jsonl

#: Eight words a row, so a row's prompt is estimated at 8 * 1.33 tokens.
ROWS = [{"question": f"Row {i} asks what two plus two is", "answer": "4"} for i in range(10)]
#: Unreachable on purpose: a dry run must not send a request.
NO_SERVER = "http://127.0.0.1:1"
COST = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}


def write_task(tmp_path, generation=None, cost=COST, rate_limits=None):
    task = {
        "name": "gsm8k",
        "api_url": NO_SERVER,
        "model": "gpt-4",
        "rate_limits": rate_limits or {"rpm": 100},
        "prompt": {"system": "Solve it", "user": "{question}"},
        "generation": generation or {"scheme": "greedy", "max_tokens": 512},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "solution",
    }
    if cost is not None:
        task["cost"] = cost
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    return path


def dry_run(config, tmp_path, *extra, rows=ROWS):
    data = write_jsonl(tmp_path / "data.jsonl", rows)
    output = tmp_path / "out.jsonl"
    process = run_cli("--config", config, "--input", data, "--output", output,
                      "--dry-run", *extra)
    assert process.returncode == 0, process.stderr
    assert not output.exists(), "a dry run writes no results"
    return json.loads(process.stdout)


def test_the_estimate_covers_tokens_cost_and_time(tmp_path):
    estimate = dry_run(write_task(tmp_path), tmp_path)

    assert estimate["tasks"]["gsm8k"] == {
        "inputs": 10,
        "est_prompt_tokens": 133,
        "est_completion_tokens": 5120,
        "est_total_tokens": 5253,
        "est_cost": 0.15,
    }
    assert estimate["total_inputs"] == 10
    assert estimate["est_total_tokens"] == 5253
    assert estimate["est_total_cost"] == 0.15
    assert estimate["est_time_minutes"] == 0.1, "ten rows through 100 requests a minute"


def test_rejection_sampling_plans_for_its_worst_case(tmp_path):
    generation = {"scheme": "rejection", "temperature": 0.7, "max_tokens": 512, "n": 5}
    estimate = dry_run(write_task(tmp_path, generation=generation), tmp_path)

    assert estimate["est_time_minutes"] == 0.5, "up to five attempts a row"
    assert estimate["tasks"]["gsm8k"]["est_completion_tokens"] == 5120


def test_a_task_without_cost_rates_estimates_no_cost(tmp_path):
    estimate = dry_run(write_task(tmp_path, cost=None), tmp_path)
    assert estimate["est_total_cost"] == 0.0


def test_a_task_without_rpm_is_left_out_of_the_time_estimate(tmp_path):
    estimate = dry_run(write_task(tmp_path, rate_limits={"max_concurrent": 4}), tmp_path)
    assert estimate["est_time_minutes"] == 0.0


def test_a_broken_input_is_reported_before_anything_is_estimated(tmp_path):
    config = write_task(tmp_path)
    data = write_jsonl(tmp_path / "data.jsonl", [{"text": "no question here"}])
    process = run_cli("--config", config, "--input", data,
                      "--output", tmp_path / "out.jsonl", "--dry-run")

    assert process.returncode == 1
    assert "question" in process.stderr


def test_a_multi_task_config_is_estimated_per_task(tmp_path):
    defaults = {
        "api_url": NO_SERVER,
        "model": "gpt-4",
        "rate_limits": {"rpm": 100},
        "cost": COST,
        "generation": {"scheme": "greedy", "max_tokens": 512},
        "output_field": "solution",
        "prompt": {"system": "Solve it", "user": "{question}"},
    }
    config = tmp_path / "multi.yaml"
    config.write_text(yaml.safe_dump({"defaults": defaults, "tasks": {"a": {}, "b": {}}}))
    data = write_jsonl(tmp_path / "data.jsonl", ROWS)
    process = run_cli("--config", config, "--input", f"a={data}", "--input", f"b={data}",
                      "--output", tmp_path / "results", "--dry-run")

    assert process.returncode == 0, process.stderr
    estimate = json.loads(process.stdout)
    assert list(estimate["tasks"]) == ["a", "b"]
    assert estimate["total_inputs"] == 20
    assert estimate["est_total_cost"] == 0.3
    assert estimate["est_time_minutes"] == 0.1, "the tasks run at the same time"
