"""End-to-end runs exercising the rate limits, the budget, and progress output."""

import json
import re

import yaml
from conftest import read_results, run_cli, write_jsonl

ROWS = [{"question": f"Row {i}: compute ANSWER={i + 1}", "answer": str(i + 1)} for i in range(12)]
EVALUATION = {"type": "exact_match", "answer_field": "answer", "extract": "last_number"}
PROGRESS_LINE = re.compile(
    r"^\[(\d+)/12\] \d+% complete \| \d+ passed, \d+ failed \| [\d.]+ rpm(.*) \| ETA: \d+s$"
)


def write_task(tmp_path, api_url, rate_limits=None, cost=None, evaluation=EVALUATION, **extra):
    task = {
        "name": "mock_task",
        "api_url": api_url,
        "model": "gpt-4",
        "rate_limits": rate_limits or {"rpm": 600},
        "prompt": {"system": "Solve it. Answer after ####.", "user": "{question}"},
        "generation": {"scheme": "greedy", "max_tokens": 64},
        "output_field": "solution",
        **extra,
    }
    if evaluation is not None:
        task["evaluation"] = evaluation
    if cost is not None:
        task["cost"] = cost
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    return path


def run_task(config, tmp_path, *extra, rows=ROWS):
    data = write_jsonl(tmp_path / "data.jsonl", rows)
    output = tmp_path / "out.jsonl"
    process = run_cli("--config", config, "--input", data, "--output", output, *extra)
    assert process.returncode == 0, process.stderr
    return read_results(output), json.loads(process.stdout), process.stderr


def test_max_concurrent_caps_requests_in_flight(tmp_path, server):
    """Two at a time through a 0.25s backend takes at least six rounds."""
    config = write_task(tmp_path, server(workers=12, delay=0.25), {"max_concurrent": 2})
    results, summary, _ = run_task(config, tmp_path)

    assert len(results) == len(ROWS)
    assert summary["elapsed_seconds"] >= 1.0, summary


def test_a_task_without_rpm_is_not_request_limited(tmp_path, server):
    config = write_task(tmp_path, server(workers=12, delay=0.05), {"max_concurrent": 12})
    results, summary, _ = run_task(config, tmp_path)

    assert len(results) == len(ROWS)
    assert summary["elapsed_seconds"] < 1.0, summary


def test_the_token_window_is_freed_by_what_requests_actually_used(tmp_path, server):
    """Reserving 1010 tokens a request, twelve rows would not fit in one minute.

    They finish anyway because each response reports 15 tokens, which replaces
    the estimate in the window.
    """
    rate_limits = {"rpm": 600, "tpm": 2000}
    config = write_task(tmp_path, server(workers=12, delay=0.05), rate_limits)
    results, summary, _ = run_task(config, tmp_path, "--max-tokens", "1000")

    assert len(results) == len(ROWS)
    assert summary["elapsed_seconds"] < 30.0, summary


def test_cost_is_reported_per_call(tmp_path, server):
    cost = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
    config = write_task(tmp_path, server("--prompt-tokens", "1000", "--completion-tokens", "1000"),
                        cost=cost)
    _, summary, _ = run_task(config, tmp_path)

    assert summary["cost"] == {
        "total": 0.48,
        "prompt": 0.12,
        "completion": 0.36,
        "budget": None,
        "budget_remaining": None,
        "budget_exceeded": False,
    }


def test_judge_calls_are_charged_too(tmp_path, server):
    cost = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
    evaluation = {
        "type": "llm_judge",
        "judge_prompt": {"system": "Score it.", "user": "Rate {__response__}"},
        "threshold": 7,
    }
    config = write_task(tmp_path, server("--prompt-tokens", "1000", "--completion-tokens", "1000"),
                        cost=cost, evaluation=evaluation)
    _, summary, _ = run_task(config, tmp_path)

    assert summary["total_api_calls"] == 2 * len(ROWS)
    assert summary["cost"]["total"] == 0.96, "one generation and one judge call per row"


def test_a_run_without_cost_configuration_omits_it(tmp_path, server):
    config = write_task(tmp_path, server())
    _, summary, _ = run_task(config, tmp_path)
    assert "cost" not in summary


def test_the_budget_stops_the_run_and_keeps_what_finished(tmp_path, server):
    """Each row costs $0.04, so the third row takes the total past a $0.10 budget."""
    cost = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03, "budget": 0.1}
    config = write_task(tmp_path, server("--prompt-tokens", "1000", "--completion-tokens", "1000"),
                        {"max_concurrent": 1}, cost=cost)
    results, summary, _ = run_task(config, tmp_path)

    assert [result["input"] for result in results] == ROWS[:3]
    assert summary["total"] == 3
    assert summary["cost"]["budget_exceeded"] is True
    assert summary["cost"]["budget_remaining"] == -0.02


def test_the_budget_flag_overrides_the_config(tmp_path, server):
    cost = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03, "budget": 100.0}
    config = write_task(tmp_path, server("--prompt-tokens", "1000", "--completion-tokens", "1000"),
                        {"max_concurrent": 1}, cost=cost)
    results, summary, _ = run_task(config, tmp_path, "--budget", "0.05")

    assert len(results) == 2
    assert summary["cost"]["budget"] == 0.05
    assert summary["cost"]["budget_exceeded"] is True


def test_progress_is_reported_to_stderr(tmp_path, server):
    cost = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
    config = write_task(
        tmp_path,
        server("--prompt-tokens", "1000", "--completion-tokens", "1000", workers=4, delay=0.1),
        cost=cost,
    )
    _, summary, stderr = run_task(config, tmp_path, "--progress")

    lines = stderr.splitlines()
    matches = [PROGRESS_LINE.match(line) for line in lines]
    assert all(matches), lines
    assert int(matches[-1].group(1)) == len(ROWS), "the last update covers every row"
    assert matches[-1].group(2) == f" | ${summary['cost']['total']:.2f} spent"


def test_progress_omits_the_fields_a_run_has_nothing_for(tmp_path, server):
    config = write_task(tmp_path, server(), evaluation=None)
    _, _, stderr = run_task(config, tmp_path, "--progress")

    assert all(re.match(r"^\[\d+/12\] \d+% complete \| [\d.]+ rpm \| ETA: \d+s$", line)
               for line in stderr.splitlines()), stderr


def test_a_quiet_run_prints_no_progress(tmp_path, server):
    config = write_task(tmp_path, server())
    _, _, stderr = run_task(config, tmp_path)
    assert stderr == ""
