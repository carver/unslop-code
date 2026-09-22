"""`--dry-run`: validate, count, estimate, and make no API calls."""

from __future__ import annotations


from fake_server import FakeAPIServer, always
from conftest import GSM8K_TASK, MMLU_TASK, base_config, multi_config

SYSTEM_WORDS = len("Solve the math problem. Put your final answer after ####.".split())
RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}


def _rows(write_input, count=4):
    return write_input([{"question": f"question number {i}", "answer": "5"} for i in range(count)])


def _expected_prompt_tokens(count, words_per_row):
    return round(count * words_per_row * 1.33)


# Spec: "validate config and inputs, but make no API calls"
def test_dry_run_sends_no_requests(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, _rows(write_input), "--dry-run")
        calls = len(api.requests)

    assert calls == 0
    assert result.returncode == 0


# Spec: "print the estimate JSON to stdout and exit `0`"
def test_dry_run_writes_no_output_file(write_config, write_input, run_cli):
    config = write_config(base_config("http://unused"))
    result = run_cli(config, _rows(write_input), "--dry-run")

    assert result.returncode == 0
    assert not result.output_path.exists()


# Spec: "validate config and inputs" - a broken config still fails with 1
def test_dry_run_still_reports_config_errors(write_config, write_input, run_cli):
    config_map = base_config("http://unused")
    config_map["task"].pop("model")
    result = run_cli(write_config(config_map), _rows(write_input), "--dry-run")

    assert result.returncode == 1


# Spec: "count input rows per task"
def test_dry_run_counts_input_rows(write_config, write_input, run_cli):
    config = write_config(base_config("http://unused"))
    result = run_cli(config, _rows(write_input, 7), "--dry-run")

    assert result.summary["tasks"]["gsm8k_solve"]["inputs"] == 7
    assert result.summary["total_inputs"] == 7


# Spec: "estimate prompt tokens as `average prompt word count * 1.33`"
def test_prompt_token_estimate_uses_the_word_factor(write_config, write_input, run_cli):
    config = write_config(base_config("http://unused"))
    result = run_cli(config, _rows(write_input, 4), "--dry-run")

    words_per_row = SYSTEM_WORDS + len("question number 0".split())
    assert result.summary["tasks"]["gsm8k_solve"]["est_prompt_tokens"] == _expected_prompt_tokens(
        4, words_per_row
    )


# Spec: "estimate total tokens as estimated prompt tokens plus `max_tokens`"
def test_completion_and_total_token_estimates(write_config, write_input, run_cli):
    config = write_config(base_config("http://unused"))
    result = run_cli(config, _rows(write_input, 4), "--dry-run")

    task = result.summary["tasks"]["gsm8k_solve"]
    assert task["est_completion_tokens"] == 4 * 512
    assert task["est_total_tokens"] == task["est_prompt_tokens"] + task["est_completion_tokens"]
    assert result.summary["est_total_tokens"] == task["est_total_tokens"]


# Spec: "estimate cost using the configured cost rates"
def test_cost_estimate_uses_the_configured_rates(write_config, write_input, run_cli):
    config = write_config(base_config("http://unused", cost=RATES))
    result = run_cli(config, _rows(write_input, 4), "--dry-run")

    task = result.summary["tasks"]["gsm8k_solve"]
    expected = task["est_prompt_tokens"] / 1000 * 0.01 + task["est_completion_tokens"] / 1000 * 0.03
    assert task["est_cost"] == round(expected, 2)
    assert result.summary["est_total_cost"] == round(expected, 2)


# Spec: "estimate time in minutes as `total_inputs * avg_attempts / rpm`,
# where `avg_attempts` is `1` for `greedy` and `sample`"
def test_time_estimate_for_single_attempt_schemes(write_config, write_input, run_cli):
    config = write_config(base_config("http://unused", rpm=100))
    result = run_cli(config, _rows(write_input, 50), "--dry-run")

    assert result.summary["est_time_minutes"] == round(50 * 1 / 100, 1)


# Spec: "`avg_attempts` is ... `n` for rejection worst-case planning"
def test_time_estimate_multiplies_rejection_by_n(write_config, write_input, run_cli):
    config_map = base_config("http://unused", rpm=100)
    config_map["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 4}
    result = run_cli(write_config(config_map), _rows(write_input, 50), "--dry-run")

    assert result.summary["est_time_minutes"] == round(50 * 4 / 100, 1)


# Spec: "estimate total tokens as estimated prompt tokens plus `max_tokens`"
# - the attempt factor is not applied to tokens (T97)
def test_rejection_token_estimate_is_a_single_attempt(write_config, write_input, run_cli):
    config_map = base_config("http://unused", rpm=100)
    config_map["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 4}
    result = run_cli(write_config(config_map), _rows(write_input, 5), "--dry-run")

    assert result.summary["tasks"]["gsm8k_solve"]["est_completion_tokens"] == 5 * 512


# Spec: dry-run totals aggregate every selected task
def test_multi_task_estimates_are_reported_per_task_and_totalled(write_config, write_input, run_argv):
    config_map = multi_config("http://unused", {"gsm8k": GSM8K_TASK, "mmlu": MMLU_TASK})
    config_map["defaults"]["cost"] = RATES
    config = write_config(config_map)
    gsm8k = write_input([{"question": "q", "answer": "5"}] * 3, name="gsm8k.jsonl")
    mmlu = write_input(
        [{"question": "q", "a": "1", "b": "2", "c": "3", "d": "4", "answer": "B"}] * 2,
        name="mmlu.jsonl",
    )
    result = run_argv(
        "--config", config, "--input", f"gsm8k={gsm8k}", "--input", f"mmlu={mmlu}", "--dry-run"
    )

    tasks = result.summary["tasks"]
    assert sorted(tasks) == ["gsm8k", "mmlu"]
    assert result.summary["total_inputs"] == 5
    assert result.summary["est_total_tokens"] == sum(t["est_total_tokens"] for t in tasks.values())
    assert result.summary["est_total_cost"] == round(sum(t["est_cost"] for t in tasks.values()), 2)


# Spec: "estimate cost using the configured cost rates" - with no rates the
# estimate is zero rather than absent
def test_cost_estimate_is_zero_without_rates(write_config, write_input, run_cli):
    config = write_config(base_config("http://unused"))
    result = run_cli(config, _rows(write_input, 2), "--dry-run")

    assert result.summary["est_total_cost"] == 0.0


# Spec: "total_inputs * avg_attempts / rpm" with RPM limiting disabled falls
# back to the historical default rate (T99)
def test_time_estimate_without_rpm(write_config, write_input, run_cli):
    config_map = base_config("http://unused")
    config_map["task"].pop("rpm")
    result = run_cli(write_config(config_map), _rows(write_input, 60), "--dry-run")

    assert result.summary["est_time_minutes"] == 1.0
