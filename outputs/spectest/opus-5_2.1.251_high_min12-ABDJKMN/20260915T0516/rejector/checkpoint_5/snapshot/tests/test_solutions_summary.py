"""Part 3 summary: total_solutions and avg_solutions_per_input."""
import threading

from conftest import (icl_block, make_config, make_multi_config,
                      marker_setups)
from mock_api import MockAPI, always, chat_response

ROWS = [{"question": "q", "answer": "42"}]
SAMPLE = dict(scheme="sample", temperature=0.7)
REJECT = dict(scheme="rejection", temperature=0.7)


def sequence_per_row(mapping, default=("#### 0",)):
    counts = {}
    lock = threading.Lock()

    def responder(payload, i):
        user = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                user = m.get("content", "")
        with lock:
            k = counts.get(user, 0)
            counts[user] = k + 1
        seq = mapping.get(user, default)
        item = seq[k] if k < len(seq) else seq[-1]
        if isinstance(item, int):
            return item, {"error": "boom"}
        return 200, chat_response(item)
    return responder


def sample_tasks(**extra):
    base = {"prompt": {"system": "S", "user": "{question}"},
            "generation": {"scheme": "sample", "temperature": 0.7},
            "evaluation": {"type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"},
            "output_field": "solution"}
    base.update(extra)
    return {"gsm8k": base}


# Spec: "Per-task summary fields gain: total, total_solutions,
#        avg_solutions_per_input, total_api_calls"
# Context: Output Changes.
def test_per_task_block_reports_solution_totals(multi):
    rows = [{"question": "a", "answer": "42"},
            {"question": "b", "answer": "42"}]
    config = make_multi_config(tasks=sample_tasks(num_solutions=3))
    with MockAPI(always("#### 42")) as api:
        config["defaults"]["api_url"] = api.url
        run = multi.run(config, {"gsm8k": rows})
    assert run.returncode == 0, run.stderr
    block = run.summary["tasks"]["gsm8k"]
    assert block["total"] == 2
    assert block["total_solutions"] == 6
    assert block["avg_solutions_per_input"] == 3.0
    assert block["total_api_calls"] == 6


# Spec: avg_solutions_per_input is total_solutions / total (450/100 = 4.5).
# Context: Output Changes.
def test_avg_solutions_per_input_is_the_mean_over_rows(multi):
    # row "a" collects 2 solutions, row "b" collects 1: 3 / 2 = 1.5.
    rows = [{"question": "a", "answer": "42"},
            {"question": "b", "answer": "42"}]
    responder = sequence_per_row({"a": ["#### 42", "#### 42", "#### 0"],
                                  "b": ["#### 42", "#### 0", "#### 0"]})
    config = make_multi_config(tasks=sample_tasks(
        num_solutions=2,
        generation={"scheme": "rejection", "temperature": 0.7,
                    "max_attempts": 3}))
    with MockAPI(responder) as api:
        config["defaults"]["api_url"] = api.url
        run = multi.run(config, {"gsm8k": rows})
    assert run.returncode == 0, run.stderr
    block = run.summary["tasks"]["gsm8k"]
    assert block["total_solutions"] == 3
    assert block["avg_solutions_per_input"] == 1.5


# T52: `passed`/`failed` stay row counts -- a row passes when it collected at
# least one passing solution.
def test_task_block_keeps_row_level_passed_and_failed(multi):
    rows = [{"question": "a", "answer": "42"},
            {"question": "b", "answer": "42"}]
    responder = sequence_per_row({"a": ["#### 42", "#### 42"],
                                  "b": ["#### 0", "#### 0"]})
    config = make_multi_config(tasks=sample_tasks(
        num_solutions=2,
        generation={"scheme": "rejection", "temperature": 0.7,
                    "max_attempts": 2}))
    with MockAPI(responder) as api:
        config["defaults"]["api_url"] = api.url
        run = multi.run(config, {"gsm8k": rows})
    assert run.returncode == 0, run.stderr
    block = run.summary["tasks"]["gsm8k"]
    assert block["passed"] == 1
    assert block["failed"] == 1
    assert block["total"] == 2


# Spec: "total_api_calls" counts every HTTP call the task made.
# Context: Output Changes.
def test_total_api_calls_counts_every_attempt(multi):
    config = make_multi_config(tasks=sample_tasks(num_solutions=4))
    with MockAPI(always("#### 42")) as api:
        config["defaults"]["api_url"] = api.url
        run = multi.run(config, {"gsm8k": ROWS})
    assert run.returncode == 0, run.stderr
    assert run.summary["tasks"]["gsm8k"]["total_api_calls"] == 4
    assert api.call_count == 4


# T53: the new fields also appear in the aggregate summary, and legacy-format
# rows count one solution each.
def test_single_task_summary_reports_solution_totals(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=3, **SAMPLE),
                       ROWS)
    assert run.returncode == 0, run.stderr
    summary = run.summary
    assert summary["total_solutions"] == 3
    assert summary["avg_solutions_per_input"] == 3.0


def test_part_1_rows_count_one_solution_each(run_tool):
    rows = [{"question": "a", "answer": "42"},
            {"question": "b", "answer": "99"}]
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, n=1, **REJECT), rows)
    assert run.returncode == 0, run.stderr
    summary = run.summary
    # row "b" fails and writes output null, contributing no solution.
    assert summary["total_solutions"] == 1
    assert summary["avg_solutions_per_input"] == 0.5


def test_part_1_top_level_fields_are_still_present(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=2, **SAMPLE),
                       ROWS)
    assert run.returncode == 0, run.stderr
    for key in ("total", "passed", "failed", "total_prompt_tokens",
                "total_completion_tokens", "total_api_calls",
                "elapsed_seconds", "throughput_rpm"):
        assert key in run.summary


def test_avg_solutions_per_input_is_zero_for_an_empty_input(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=2, **SAMPLE),
                       [])
    assert run.returncode == 0, run.stderr
    assert run.summary["total_solutions"] == 0
    assert run.summary["avg_solutions_per_input"] == 0


def test_icl_task_summary_counts_solutions(multi):
    setups = marker_setups(["A", "B"])
    config = make_multi_config(tasks=sample_tasks(
        icl=icl_block(setups), num_solutions=2))
    with MockAPI(always("#### 42")) as api:
        config["defaults"]["api_url"] = api.url
        run = multi.run(config, {"gsm8k": ROWS})
    assert run.returncode == 0, run.stderr
    block = run.summary["tasks"]["gsm8k"]
    assert block["total_solutions"] == 2
    assert block["avg_solutions_per_input"] == 2.0
