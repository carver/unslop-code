"""Spec section: Dry Run (`--dry-run`)."""
from __future__ import annotations

import copy

import pytest

from conftest import GSM8K_TASK, MMLU_TASK, base_config, multi_config, rows_of
from mock_server import MockAPI, always

SYSTEM = "Solve the math problem. Put your final answer after ####."
COST = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}


def words_per_row(system, user_rendered):
    return len(f"{system} {user_rendered}".split())


# ---------------------------------------------------------------------------
# Phrase: "validate config and inputs, but make no API calls" /
#         "print the estimate JSON to stdout and exit `0`"
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_makes_no_api_calls(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(5))
        res = run_tool(cfg, data, extra=["--dry-run"])
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 0
    assert not res.output_exists, "a dry run wrote an output file"
    assert isinstance(res.summary, dict)


# ---------------------------------------------------------------------------
# Phrase: the estimate example - tasks.<name>.{inputs, est_prompt_tokens,
#         est_completion_tokens, est_total_tokens, est_cost} plus total_inputs,
#         est_total_tokens, est_total_cost, est_time_minutes
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_estimate_shape(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url, cost=dict(COST)))
        data = write_input(rows_of(4))
        res = run_tool(cfg, data, extra=["--dry-run"])
    assert res.returncode == 0, res
    estimate = res.summary
    for key in ("tasks", "total_inputs", "est_total_tokens", "est_total_cost",
                "est_time_minutes"):
        assert key in estimate, estimate
    task = estimate["tasks"]["gsm8k_solve"]
    for key in ("inputs", "est_prompt_tokens", "est_completion_tokens",
                "est_total_tokens", "est_cost"):
        assert key in task, task


# ---------------------------------------------------------------------------
# Phrase: "count input rows per task"
# Phrase: "estimate prompt tokens as `average prompt word count * 1.33`"
# Phrase: "estimate total tokens as estimated prompt tokens plus `max_tokens`"
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_token_estimates(run_tool, write_config, write_input):
    inputs = [{"question": "what is two plus two", "answer": "4"},
              {"question": "how many cats", "answer": "3"}]
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url,
                                       generation={"max_tokens": 256}))
        data = write_input(inputs)
        res = run_tool(cfg, data, extra=["--dry-run"])
    assert res.returncode == 0, res
    task = res.summary["tasks"]["gsm8k_solve"]
    avg_words = sum(words_per_row(SYSTEM, row["question"])
                    for row in inputs) / len(inputs)
    est_prompt = avg_words * 1.33 * len(inputs)
    est_completion = 256 * len(inputs)
    assert task["inputs"] == 2
    assert task["est_prompt_tokens"] == pytest.approx(est_prompt, rel=1e-3)
    assert task["est_completion_tokens"] == pytest.approx(est_completion)
    assert task["est_total_tokens"] == pytest.approx(est_prompt
                                                     + est_completion,
                                                     rel=1e-3)
    assert res.summary["total_inputs"] == 2
    assert res.summary["est_total_tokens"] == pytest.approx(
        task["est_total_tokens"], rel=1e-9)


# ---------------------------------------------------------------------------
# Phrase: "estimate cost using the configured cost rates"
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_cost_estimate(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url, cost=dict(COST),
                                       generation={"max_tokens": 500}))
        data = write_input(rows_of(10))
        res = run_tool(cfg, data, extra=["--dry-run"])
    assert res.returncode == 0, res
    task = res.summary["tasks"]["gsm8k_solve"]
    expected = (task["est_prompt_tokens"] / 1000 * 0.01
                + task["est_completion_tokens"] / 1000 * 0.03)
    assert task["est_cost"] == pytest.approx(expected, rel=1e-6)
    assert res.summary["est_total_cost"] == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# Phrase: "estimate time in minutes as `total_inputs * avg_attempts / rpm`,
#          where `avg_attempts` is `1` for `greedy` and `sample`"
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_time_estimate_greedy(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url, rpm=120))
        data = write_input(rows_of(30))
        res = run_tool(cfg, data, extra=["--dry-run"])
    assert res.returncode == 0, res
    assert res.summary["est_time_minutes"] == pytest.approx(30 * 1 / 120,
                                                            rel=1e-6)


# ---------------------------------------------------------------------------
# Phrase: "`avg_attempts` is ... `n` for rejection worst-case planning; prefer
#          precision over rounding"
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_time_estimate_rejection(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(
            api.url, rpm=90,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 4}))
        data = write_input(rows_of(7))
        res = run_tool(cfg, data, extra=["--dry-run"])
    assert res.returncode == 0, res
    expected = 7 * 4 / 90
    assert res.summary["est_time_minutes"] == pytest.approx(expected,
                                                            rel=1e-6)
    # precision, not a rounded-off 0.3
    assert res.summary["est_time_minutes"] != round(expected, 1)


# ---------------------------------------------------------------------------
# Phrase: "count input rows per task" (multi-task configs)
# Context: Dry Run.
# ---------------------------------------------------------------------------
def test_dry_run_multi_task(run_tool, write_config, write_input, workdir):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(multi_config(api.url,
                                        {"gsm8k": copy.deepcopy(GSM8K_TASK),
                                         "mmlu": copy.deepcopy(MMLU_TASK)},
                                        defaults={"cost": dict(COST)}))
        a = write_input(rows_of(6), name="a.jsonl")
        b = write_input([{"question": f"q{i}", "a": "1", "b": "2", "c": "3",
                          "d": "4", "answer": "A"} for i in range(4)],
                        name="b.jsonl")
        res = run_tool(cfg, [f"gsm8k={a}", f"mmlu={b}"],
                       output=str(workdir / "out"), extra=["--dry-run"])
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 0
    estimate = res.summary
    assert set(estimate["tasks"]) == {"gsm8k", "mmlu"}
    assert estimate["tasks"]["gsm8k"]["inputs"] == 6
    assert estimate["tasks"]["mmlu"]["inputs"] == 4
    assert estimate["total_inputs"] == 10
    assert estimate["est_total_tokens"] == pytest.approx(
        estimate["tasks"]["gsm8k"]["est_total_tokens"]
        + estimate["tasks"]["mmlu"]["est_total_tokens"], rel=1e-9)
    assert estimate["est_total_cost"] == pytest.approx(
        estimate["tasks"]["gsm8k"]["est_cost"]
        + estimate["tasks"]["mmlu"]["est_cost"], rel=1e-9)


# ---------------------------------------------------------------------------
# Phrase: "validate config and inputs"
# Context: Dry Run.  A broken config or a row missing a template field is
# still a usage error (exit 1).
# ---------------------------------------------------------------------------
def test_dry_run_validates_config(run_tool, write_config, write_input):
    cfg_dict = base_config("http://127.0.0.1:1")
    del cfg_dict["task"]["prompt"]
    cfg = write_config(cfg_dict)
    data = write_input(rows_of(2))
    res = run_tool(cfg, data, extra=["--dry-run"])
    assert res.returncode == 1, res
    assert "prompt" in res.stderr


def test_dry_run_validates_inputs(run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1"))
    data = write_input([{"not_question": "x", "answer": "5"}])
    res = run_tool(cfg, data, extra=["--dry-run"])
    assert res.returncode == 1, res
    assert res.stderr.strip()
