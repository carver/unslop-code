"""Part 2 summary: the `tasks` object, aggregation, ordering, scheduling."""
import json

import pytest

from conftest import make_config, make_multi_config, judge_task, script_task
from mock_api import (MockAPI, always, by_text, chat_response, message_text,
                      per_question, status)

GSM = [{"question": "2+2?", "answer": "4"}]
MML = [{"question": "capital?", "answer": "B"}]
REVIEW = [{"prompt_text": "Write about cats", "criteria": "clarity"}]


# Spec: "The stdout summary now includes a `tasks` object keyed by executed
# task name."
# Context: Summary And Scheduling.
def test_summary_has_a_tasks_object_keyed_by_task_name(multi):
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    assert sorted(run.summary["tasks"]) == ["gsm8k", "mmlu"]


# Spec: the per-task block shape
#   "gsm8k": {"total": 100, "passed": 85, "failed": 15, "total_api_calls": 142}
# Context: Summary And Scheduling.
def test_per_task_block_has_total_passed_failed_and_api_calls(multi):
    rows = [{"question": "2+2?", "answer": "4"},
            {"question": "2+2?", "answer": "5"}]
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": rows}, args=["--task", "gsm8k"])
    block = run.summary["tasks"]["gsm8k"]
    assert block == {"total": 2, "passed": 1, "failed": 1, "total_api_calls": 2}


def test_top_level_fields_from_part_1_are_still_present(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM}, args=["--task", "gsm8k"])
    summary = run.summary
    for key in ("total", "passed", "failed", "total_api_calls",
                "elapsed_seconds", "throughput_rpm", "tasks"):
        assert key in summary


def test_top_level_totals_are_the_sum_of_the_task_blocks(multi):
    gsm = [{"question": "2+2?", "answer": "4"}] * 3
    mml = [{"question": "capital?", "answer": "B"},
           {"question": "capital?", "answer": "C"}]
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": gsm, "mmlu": mml})
    summary = run.summary
    blocks = summary["tasks"].values()
    assert summary["total"] == sum(b["total"] for b in blocks) == 5
    assert summary["passed"] == sum(b["passed"] for b in blocks) == 4
    assert summary["failed"] == sum(b["failed"] for b in blocks) == 1
    assert summary["total_api_calls"] == sum(b["total_api_calls"] for b in blocks)


# Spec: "include only tasks that actually ran"
# Context: Rules, Summary And Scheduling.
def test_only_executed_tasks_appear_in_the_summary(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML}, args=["--task", "gsm8k"])
    assert list(run.summary["tasks"]) == ["gsm8k"]
    assert run.summary["total"] == 1


# Spec: "per-task `total_api_calls` includes judge calls"
# Context: Rules, Summary And Scheduling.
def test_per_task_api_calls_include_judge_calls(multi):
    cfg = make_multi_config(tasks={"review": judge_task(threshold=7)})
    with MockAPI(by_text([("Rate this response", "8")], default="essay")) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"review": REVIEW * 3})
    assert run.returncode == 0, run.stderr
    assert run.summary["tasks"]["review"]["total_api_calls"] == 6
    assert run.summary["total_api_calls"] == 6


def test_per_task_api_calls_include_retries(multi):
    def flaky(payload, i):
        if message_text(payload, "user") == "2+2?" and i < 2:
            return 500, {"error": "boom"}
        return 200, chat_response("#### 4")

    cfg = make_multi_config()
    with MockAPI(flaky) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    assert run.summary["tasks"]["gsm8k"]["total_api_calls"] >= 2
    assert run.summary["total_api_calls"] == api.call_count


def test_task_api_calls_are_attributed_to_the_right_task(multi):
    gsm = [{"question": "2+2?", "answer": "4"}] * 4
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": gsm, "mmlu": MML})
    assert run.summary["tasks"]["gsm8k"]["total_api_calls"] == 4
    assert run.summary["tasks"]["mmlu"]["total_api_calls"] == 1


# Spec: "within each task's output file, row order must still match input
# order"
# Context: Rules, Summary And Scheduling.
def test_row_order_matches_input_order_per_task(multi):
    gsm = [{"question": "q%d" % i, "answer": str(i)} for i in range(8)]
    mml = [{"question": "m%d" % i, "answer": "B"} for i in range(8)]

    def responder(payload, i):
        user = message_text(payload, "user")
        return 200, chat_response("#### %s" % user[1:] if user.startswith("q")
                                  else "B")

    with MockAPI(responder, service_seconds=0.02) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": gsm, "mmlu": mml})
    assert run.returncode == 0, run.stderr
    assert [r["input"] for r in run.rows("gsm8k")] == gsm
    assert [r["input"] for r in run.rows("mmlu")] == mml
    assert all(r["result"]["passed"] for r in run.rows("gsm8k"))


# Spec: "requests from different tasks may run concurrently and may be
# interleaved"
# Context: Rules, Summary And Scheduling.
def test_requests_from_different_tasks_overlap(multi):
    with MockAPI(always("#### 4"), service_seconds=0.5) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    assert api.max_concurrent == 2


def test_elapsed_spans_all_tasks(multi):
    with MockAPI(always("#### 4"), service_seconds=0.3) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML})
    summary = run.summary
    assert summary["elapsed_seconds"] >= 0.3
    expected = summary["total_api_calls"] / summary["elapsed_seconds"] * 60.0
    assert summary["throughput_rpm"] == pytest.approx(expected, rel=0.15)


# Spec: "After processing finishes, print one JSON summary object to stdout."
# Context: Part 1 output rule, still one object for multi-task runs.
def test_multi_task_run_prints_exactly_one_json_object(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML})
    lines = [l for l in run.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1
    assert isinstance(json.loads(lines[0]), dict)


# T23: a single-task config reports its one task under the same key.
def test_single_task_config_summary_includes_a_tasks_object(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, name="gsm8k_solve"),
                       [{"question": "q", "answer": "5"}])
    summary = run.summary
    assert summary["tasks"] == {"gsm8k_solve": {
        "total": 1, "passed": 1, "failed": 0, "total_api_calls": 1}}


# T24: a selected task with an empty input file still ran.
def test_task_with_no_rows_reports_zeros(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": []})
    assert run.returncode == 0, run.stderr
    assert run.summary["tasks"]["mmlu"] == {
        "total": 0, "passed": 0, "failed": 0, "total_api_calls": 0}
    assert run.rows("mmlu") == []


def test_failed_rows_are_counted_per_task(multi):
    def responder(payload, i):
        if message_text(payload, "user") == "capital?":
            return 500, {"error": "boom"}
        return 200, chat_response("#### 4")

    with MockAPI(responder) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    assert run.summary["tasks"]["gsm8k"] == {
        "total": 1, "passed": 1, "failed": 0, "total_api_calls": 1}
    assert run.summary["tasks"]["mmlu"]["failed"] == 1
    assert run.rows("mmlu")[0]["output"] is None
