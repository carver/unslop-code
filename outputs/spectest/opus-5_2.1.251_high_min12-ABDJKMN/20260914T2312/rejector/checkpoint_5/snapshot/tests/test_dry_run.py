"""Dry Run section: --dry-run estimates without calling the API."""

import json
import os

import pytest

import fake_api

# 99 words of question plus a one-word system prompt is 100 words a row, so
# `average prompt word count * 1.33` lands on a whole 133 tokens.
QUESTION = " ".join("w%d" % i for i in range(99))
PROMPT = {"system": "Solve", "user": "{question}"}
RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}


def rows_of(n):
    return [{"question": QUESTION, "answer": "5"} for _ in range(n)]


def estimate_task(**over):
    task = {"prompt": PROMPT, "generation": {"max_tokens": 512}, "rpm": 60}
    task.update(over)
    return task


# ---------------------------------------------------------------------------
# Spec: "validate config and inputs, but make no API calls"
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_makes_no_api_calls(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=estimate_task(), rows=rows_of(10),
                       extra=["--dry-run"], check=0)
    assert api.call_count == 0
    assert res.returncode == 0


# ---------------------------------------------------------------------------
# Spec: "print the estimate JSON to stdout and exit `0`"
# Spec example keys: tasks/<name>/{inputs, est_prompt_tokens,
#   est_completion_tokens, est_total_tokens, est_cost}, total_inputs,
#   est_total_tokens, est_total_cost, est_time_minutes
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_estimate_shape(run_task):
    res = run_task(task=estimate_task(cost=dict(RATES)), rows=rows_of(10),
                   extra=["--dry-run"], check=0)
    est = res.summary
    assert set(est) >= {"tasks", "total_inputs", "est_total_tokens",
                        "est_total_cost", "est_time_minutes"}
    task = est["tasks"]["gsm8k_solve"]
    assert set(task) == {"inputs", "est_prompt_tokens", "est_completion_tokens",
                         "est_total_tokens", "est_cost"}


# ---------------------------------------------------------------------------
# Spec: "count input rows per task"
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_counts_input_rows(run_task):
    res = run_task(task=estimate_task(), rows=rows_of(7),
                   extra=["--dry-run"], check=0)
    assert res.summary["tasks"]["gsm8k_solve"]["inputs"] == 7
    assert res.summary["total_inputs"] == 7


# ---------------------------------------------------------------------------
# Spec: "estimate prompt tokens as `average prompt word count * 1.33`"
# Spec: "estimate total tokens as estimated prompt tokens plus `max_tokens`"
# Context: Dry Run.  100 words a row -> 133 prompt tokens a row; the example
# multiplies both by the input count (45000 / 512000 for 1000 inputs).
# ---------------------------------------------------------------------------
def test_dry_run_token_estimates(run_task):
    res = run_task(task=estimate_task(), rows=rows_of(10),
                   extra=["--dry-run"], check=0)
    task = res.summary["tasks"]["gsm8k_solve"]
    assert task["est_prompt_tokens"] == 1330
    assert task["est_completion_tokens"] == 5120
    assert task["est_total_tokens"] == 6450
    assert res.summary["est_total_tokens"] == 6450


# ---------------------------------------------------------------------------
# Spec: "estimate cost using the configured cost rates"
# Context: Dry Run.  1330/1000*0.01 + 5120/1000*0.03 = 0.1669.
# ---------------------------------------------------------------------------
def test_dry_run_cost_estimate(run_task):
    res = run_task(task=estimate_task(cost=dict(RATES)), rows=rows_of(10),
                   extra=["--dry-run"], check=0)
    task = res.summary["tasks"]["gsm8k_solve"]
    assert task["est_cost"] == pytest.approx(0.17, abs=0.005)
    assert res.summary["est_total_cost"] == pytest.approx(0.17, abs=0.005)


# ---------------------------------------------------------------------------
# Spec: "estimate cost using the configured cost rates"
# Context: Dry Run.  No rates configured means nothing to charge
# (AMBIGUITIES T106).
# ---------------------------------------------------------------------------
def test_dry_run_cost_without_rates(run_task):
    res = run_task(task=estimate_task(), rows=rows_of(3),
                   extra=["--dry-run"], check=0)
    assert res.summary["est_total_cost"] == 0.0
    assert res.summary["tasks"]["gsm8k_solve"]["est_cost"] == 0.0


# ---------------------------------------------------------------------------
# Spec: "estimate time in minutes as `total_inputs * avg_attempts / rpm`,
#        where `avg_attempts` is `1` for `greedy` and `sample`"
# Context: Dry Run.  60 inputs at rpm 60 is one minute.
# ---------------------------------------------------------------------------
def test_dry_run_time_estimate_for_greedy(run_task):
    res = run_task(task=estimate_task(), rows=rows_of(60),
                   extra=["--dry-run"], check=0)
    assert res.summary["est_time_minutes"] == pytest.approx(1.0)


def test_dry_run_time_estimate_for_sample(run_task):
    res = run_task(task=estimate_task(generation={"scheme": "sample",
                                                  "temperature": 0.7,
                                                  "max_tokens": 512}),
                   rows=rows_of(30), extra=["--dry-run"], check=0)
    assert res.summary["est_time_minutes"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Spec: "`avg_attempts` is ... `n` for rejection worst-case planning"
# Context: Dry Run.  30 rows x 4 attempts / rpm 60 = 2 minutes.
# ---------------------------------------------------------------------------
def test_dry_run_time_estimate_for_rejection(run_task):
    res = run_task(task=estimate_task(generation={"scheme": "rejection",
                                                  "temperature": 0.8,
                                                  "n": 4, "max_tokens": 512}),
                   rows=rows_of(30), extra=["--dry-run"], check=0)
    assert res.summary["est_time_minutes"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Spec: "validate config and inputs" -- a broken config still exits 1.
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_still_validates_the_config(run_task):
    res = run_task(task={"model": None}, extra=["--dry-run"], check=1)
    assert "error" in res.stderr.lower()


def test_dry_run_still_validates_the_input(run_cli, write_config, workdir):
    cfg = write_config({})
    res = run_cli("run", "--config", cfg, "--input",
                  str(workdir / "missing.jsonl"), check=1)
    assert "error" in res.stderr.lower()


def test_dry_run_rejects_input_rows_missing_a_placeholder(run_task):
    res = run_task(task=estimate_task(), rows=[{"answer": "5"}],
                   extra=["--dry-run"], check=1)
    assert "error" in res.stderr.lower()


# ---------------------------------------------------------------------------
# Spec: "validate config and inputs, but make no API calls" -- and write no
# results.
# Context: Dry Run (AMBIGUITIES T106).
# ---------------------------------------------------------------------------
def test_dry_run_writes_no_output_file(run_task):
    res = run_task(task=estimate_task(), rows=rows_of(2),
                   extra=["--dry-run"], check=0)
    assert not res.output_exists


# ---------------------------------------------------------------------------
# Spec: "count input rows per task" / the `tasks` object
# Context: Dry Run.  A multi-task config estimates each task separately.
# ---------------------------------------------------------------------------
def test_dry_run_multi_task(run_multi):
    res = run_multi(defaults={"cost": dict(RATES)},
                    inputs={"gsm8k": [{"question": "a b c", "answer": "5"}
                                      for _ in range(4)],
                            "mmlu": [{"question": "a b", "answer": "B"}
                                     for _ in range(6)]},
                    extra=["--dry-run"], check=0)
    est = res.summary
    assert set(est["tasks"]) == {"gsm8k", "mmlu"}
    assert est["tasks"]["gsm8k"]["inputs"] == 4
    assert est["tasks"]["mmlu"]["inputs"] == 6
    assert est["total_inputs"] == 10
    assert est["est_total_tokens"] == (est["tasks"]["gsm8k"]["est_total_tokens"]
                                       + est["tasks"]["mmlu"]["est_total_tokens"])
