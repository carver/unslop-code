"""Part 5: --dry-run estimates without touching the API."""
import pytest

from conftest import cost_block, make_config, make_multi_config
from mock_api import MockAPI, always


ROWS = [{"question": "one two three", "answer": "5"} for _ in range(4)]


def plain_config(api_url, **kw):
    """A task whose only prompt text is the row's three-word question."""
    kw.setdefault("system", None)
    kw.setdefault("max_tokens", 512)
    return make_config(api_url=api_url, **kw)


# Spec: "--dry-run ... validate config and inputs, but make no API calls"
# Context: Dry Run / Rules.
def test_dry_run_makes_no_api_calls(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(plain_config(api.url), ROWS, args=["--dry-run"])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 0


# Spec: "print the estimate JSON to stdout and exit `0`"
# Context: Dry Run / Rules.
def test_dry_run_prints_estimate_json_and_exits_zero(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(plain_config(api.url), ROWS, args=["--dry-run"])
    assert run.returncode == 0, run.stderr
    estimate = run.summary
    assert set(estimate) >= {"tasks", "total_inputs", "est_total_tokens",
                             "est_total_cost", "est_time_minutes"}


# Spec: no work is done, so no output file is written.
def test_dry_run_writes_no_output_file(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(plain_config(api.url), ROWS, args=["--dry-run"])
    assert run.returncode == 0, run.stderr
    assert not run.output_exists


# Spec: "count input rows per task"
# Context: Dry Run / Rules; the example's per-task "inputs": 1000.
def test_per_task_input_count(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(plain_config(api.url), ROWS, args=["--dry-run"])
    task = run.summary["tasks"]["gsm8k_solve"]
    assert task["inputs"] == 4
    assert run.summary["total_inputs"] == 4


# Spec: "estimate prompt tokens as `average prompt word count * 1.33`"
# Context: Dry Run / Rules. Four rows of three words each.
def test_prompt_token_estimate(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(plain_config(api.url), ROWS, args=["--dry-run"])
    task = run.summary["tasks"]["gsm8k_solve"]
    assert task["est_prompt_tokens"] == round(3 * 1.33 * 4)


# Spec: "estimate total tokens as estimated prompt tokens plus `max_tokens`"
# Context: Dry Run / Rules; the example's 557000 = 45000 + 1000 * 512.
def test_total_token_estimate(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(plain_config(api.url), ROWS, args=["--dry-run"])
    task = run.summary["tasks"]["gsm8k_solve"]
    assert task["est_completion_tokens"] == 4 * 512
    assert task["est_total_tokens"] == task["est_prompt_tokens"] + 4 * 512
    assert run.summary["est_total_tokens"] == task["est_total_tokens"]


# Spec: "estimate cost using the configured cost rates"
# Context: Dry Run / Rules.
def test_cost_estimate_uses_the_configured_rates(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(plain_config(api.url, cost=cost_block(0.01, 0.03)),
                       ROWS, args=["--dry-run"])
    task = run.summary["tasks"]["gsm8k_solve"]
    expected = (task["est_prompt_tokens"] / 1000.0 * 0.01
                + task["est_completion_tokens"] / 1000.0 * 0.03)
    assert task["est_cost"] == pytest.approx(expected)
    assert run.summary["est_total_cost"] == pytest.approx(expected)


# Spec: with no cost rates configured there is nothing to charge.
def test_cost_estimate_is_zero_without_rates(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(plain_config(api.url), ROWS, args=["--dry-run"])
    assert run.summary["tasks"]["gsm8k_solve"]["est_cost"] == 0.0
    assert run.summary["est_total_cost"] == 0.0


# Spec: "estimate time in minutes as `total_inputs * avg_attempts / rpm`,
#        where `avg_attempts` is `1` for `greedy` and `sample`"
# Context: Dry Run / Rules.
def test_time_estimate_for_greedy(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(plain_config(api.url, rpm=120), ROWS, args=["--dry-run"])
    assert run.summary["est_time_minutes"] == round(4 * 1 / 120.0, 1)


# Spec: "... and `n` for rejection worst-case planning"
# Context: Dry Run / Rules.
def test_time_estimate_for_rejection_uses_n(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(plain_config(api.url, rpm=8, scheme="rejection",
                                    temperature=0.7, n=3),
                       ROWS, args=["--dry-run"])
    assert run.summary["est_time_minutes"] == round(4 * 3 / 8.0, 1)


# Spec: "validate config and inputs" - a bad config still exits 1.
# Context: Dry Run / Rules.
def test_dry_run_still_reports_config_errors(run_tool):
    run = run_tool(make_config(model=None), ROWS, args=["--dry-run"])
    assert run.returncode == 1
    assert "error" in run.stderr.lower()


# Spec: "validate config and inputs" - a malformed input file exits 1.
def test_dry_run_still_reports_input_errors(run_tool):
    run = run_tool(make_config(), [], args=["--dry-run"],
                   input_text="{not json}\n")
    assert run.returncode == 1


# Spec: the estimate covers every task of a multi-task config.
def test_dry_run_covers_every_task(multi):
    config = make_multi_config(defaults={"cost": cost_block(0.01, 0.03)})
    run = multi.run(config,
                    {"gsm8k": [{"question": "a b", "answer": "5"}] * 2,
                     "mmlu": [{"question": "a b c", "answer": "A"}] * 3},
                    args=["--dry-run"])
    assert run.returncode == 0, run.stderr
    estimate = run.summary
    assert set(estimate["tasks"]) == {"gsm8k", "mmlu"}
    assert estimate["tasks"]["gsm8k"]["inputs"] == 2
    assert estimate["tasks"]["mmlu"]["inputs"] == 3
    assert estimate["total_inputs"] == 5
    assert estimate["est_total_tokens"] == (
        estimate["tasks"]["gsm8k"]["est_total_tokens"]
        + estimate["tasks"]["mmlu"]["est_total_tokens"])
    assert estimate["est_total_cost"] == pytest.approx(
        estimate["tasks"]["gsm8k"]["est_cost"]
        + estimate["tasks"]["mmlu"]["est_cost"])
