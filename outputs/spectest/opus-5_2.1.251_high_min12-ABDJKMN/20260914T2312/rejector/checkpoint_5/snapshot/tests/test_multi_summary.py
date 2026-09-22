"""Part 2 summary (`tasks` object) and cross-task scheduling."""

import json

import pytest

import fake_api


ROWS = {"gsm8k": [{"question": "q%d" % i, "answer": "5"} for i in range(3)],
        "mmlu": [{"question": "m%d" % i, "answer": "B"} for i in range(2)]}


# ---------------------------------------------------------------------------
# Spec: "The stdout summary now includes a `tasks` object keyed by executed
#        task name"
# Context: Summary And Scheduling.
# ---------------------------------------------------------------------------
def test_summary_includes_a_tasks_object_keyed_by_task_name(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, inputs=ROWS, check=0)
    assert set(res.summary["tasks"]) == {"gsm8k", "mmlu"}


# ---------------------------------------------------------------------------
# Spec: '"gsm8k": {"total": 100, "passed": 85, "failed": 15,
#        "total_api_calls": 142}'
# Context: Summary And Scheduling.  The per-task object's keys, which Part 3
# extends with "total_solutions" and "avg_solutions_per_input".
# ---------------------------------------------------------------------------
def test_per_task_object_keys(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, inputs=ROWS, check=0)
    assert set(res.summary["tasks"]["gsm8k"]) == {
        "total", "passed", "failed", "total_api_calls", "total_solutions",
        "avg_solutions_per_input"}


# ---------------------------------------------------------------------------
# Spec: 'tasks: {"gsm8k": {"total": 100, ...}}'
# Context: Summary And Scheduling.  Per-task `total` is that task's row count.
# ---------------------------------------------------------------------------
def test_per_task_total_is_that_tasks_row_count(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, inputs=ROWS, check=0)
    assert res.summary["tasks"]["gsm8k"]["total"] == 3
    assert res.summary["tasks"]["mmlu"]["total"] == 2


# ---------------------------------------------------------------------------
# Spec: '"passed": 85, "failed": 15' per task
# Context: Summary And Scheduling.  Per-task pass/fail counts are that task's
# own evaluation outcomes.
# ---------------------------------------------------------------------------
def test_per_task_passed_and_failed(run_multi):
    # "#### 5" passes gsm8k (last_number 5) and fails mmlu (no A-D letter).
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, inputs=ROWS, check=0)
    assert res.summary["tasks"]["gsm8k"] == {
        "total": 3, "passed": 3, "failed": 0, "total_api_calls": 3,
        "total_solutions": 3, "avg_solutions_per_input": 1.0}
    assert res.summary["tasks"]["mmlu"]["passed"] == 0
    assert res.summary["tasks"]["mmlu"]["failed"] == 2


# ---------------------------------------------------------------------------
# Spec: '{"total": 200, "passed": 170, "failed": 30, ...}' above the `tasks`
#        object
# Context: Summary And Scheduling.  The run-wide totals are the sum over the
# executed tasks.
# ---------------------------------------------------------------------------
def test_run_totals_are_the_sum_over_tasks(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, inputs=ROWS, check=0)
    summary = res.summary
    assert summary["total"] == 5
    assert summary["passed"] == sum(t["passed"]
                                    for t in summary["tasks"].values())
    assert summary["failed"] == sum(t["failed"]
                                    for t in summary["tasks"].values())


# ---------------------------------------------------------------------------
# Spec: '"total_api_calls": 350' alongside the per-task call totals
# Context: Summary And Scheduling.
# ---------------------------------------------------------------------------
def test_total_api_calls_is_the_sum_of_per_task_calls(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, inputs=ROWS, check=0)
    summary = res.summary
    assert summary["total_api_calls"] == 5
    assert sum(t["total_api_calls"]
               for t in summary["tasks"].values()) == 5


# ---------------------------------------------------------------------------
# Spec: "per-task `total_api_calls` includes judge calls"
# Context: Summary And Scheduling.
# ---------------------------------------------------------------------------
def test_per_task_api_calls_include_judge_calls(run_cli, write_multi_config,
                                                write_inputs, workdir):
    tasks = {"gsm8k": {"prompt": {"user": "{question}"},
                       "generation": {"scheme": "greedy"},
                       "evaluation": {"type": "exact_match",
                                      "answer_field": "answer",
                                      "extract": "last_number"},
                       "output_field": "solution"},
             "review": {"prompt": {"user": "{prompt_text}"},
                        "generation": {"scheme": "greedy"},
                        "evaluation": {"type": "llm_judge",
                                       "judge_prompt": {"user":
                                                        "Rate: {__response__}"},
                                       "threshold": 7,
                                       "extract": "first_number"},
                        "output_field": "response"}}

    def responder(rec):
        judge = (rec.user_content or "").startswith("Rate:")
        return 200, fake_api.completion("8" if judge else "#### 5")

    with fake_api.FakeAPI(responder) as api:
        cfg = write_multi_config({"api_url": api.url}, tasks,
                                 replace_tasks=True)
        paths = write_inputs({"gsm8k": [{"question": "q", "answer": "5"}],
                              "review": [{"prompt_text": "p"},
                                         {"prompt_text": "p2"}]})
        out = str(workdir / "results")
        argv = ["run", "--config", cfg]
        for task, path in paths.items():
            argv += ["--input", "%s=%s" % (task, path)]
        res = run_cli(*argv, "--output", out, output=out, check=0)
    assert res.summary["tasks"]["gsm8k"]["total_api_calls"] == 1
    assert res.summary["tasks"]["review"]["total_api_calls"] == 4
    assert res.summary["total_api_calls"] == 5


# ---------------------------------------------------------------------------
# Spec: "include only tasks that actually ran"
# Context: Summary And Scheduling.
# ---------------------------------------------------------------------------
def test_only_executed_tasks_appear_in_the_summary(run_cli,
                                                   write_multi_config,
                                                   write_inputs, workdir):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_multi_config({"api_url": api.url})
        paths = write_inputs({"gsm8k": ROWS["gsm8k"]})
        out = str(workdir / "results")
        res = run_cli("run", "--config", cfg, "--input",
                      "gsm8k=%s" % paths["gsm8k"], "--task", "gsm8k",
                      "--output", out, output=out, check=0)
    assert list(res.summary["tasks"]) == ["gsm8k"]
    assert res.summary["total"] == 3


# ---------------------------------------------------------------------------
# Spec: "The stdout summary now includes a `tasks` object"
# Context: Summary And Scheduling.  AMBIGUITIES T38 — the Part 1 summary keys
# are still there ("Existing behavior from Part 1 is unchanged").
# ---------------------------------------------------------------------------
def test_part1_summary_keys_are_still_present(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, inputs=ROWS, check=0)
    assert set(res.summary) == {
        "total", "passed", "failed", "total_prompt_tokens",
        "total_completion_tokens", "total_api_calls", "elapsed_seconds",
        "throughput_rpm", "tasks"}


# ---------------------------------------------------------------------------
# Spec: '"elapsed_seconds": 45.2, "throughput_rpm": 464.6'
# Context: Summary And Scheduling.  The run-wide timing fields still describe
# the whole run, across tasks.
# ---------------------------------------------------------------------------
def test_run_wide_timing_fields_cover_all_tasks(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5"), latency=0.05) as api:
        res = run_multi(api, inputs=ROWS, check=0)
    summary = res.summary
    assert summary["elapsed_seconds"] > 0
    assert summary["throughput_rpm"] == pytest.approx(
        round(summary["total_api_calls"] / summary["elapsed_seconds"] * 60, 1),
        rel=0.05)


# ---------------------------------------------------------------------------
# Spec: "requests from different tasks may run concurrently and may be
#        interleaved"
# Context: Summary And Scheduling.  Rows of both tasks are in flight at once.
# ---------------------------------------------------------------------------
def test_requests_from_different_tasks_run_concurrently(run_multi):
    rows = {"gsm8k": [{"question": "q%d" % i, "answer": "5"}
                      for i in range(4)],
            "mmlu": [{"question": "m%d" % i, "answer": "B"}
                     for i in range(4)]}
    with fake_api.FakeAPI(fake_api.always("#### 5"), latency=0.2) as api:
        res = run_multi(api, inputs=rows, check=0)
        assert api.max_inflight > 1
        # Both tasks have requests open at the same time: the first request of
        # the second task starts before the last request of the first ends.
        by_task = {}
        for rec in api.requests:
            key = "gsm8k" if rec.user_content.startswith("q") else "mmlu"
            by_task.setdefault(key, []).append(rec)
        first_mmlu = min(r.started for r in by_task["mmlu"])
        last_gsm8k = max(r.finished for r in by_task["gsm8k"])
    assert first_mmlu < last_gsm8k


# ---------------------------------------------------------------------------
# Spec: "within each task's output file, row order must still match input
#        order"
# Context: Summary And Scheduling.
# ---------------------------------------------------------------------------
def test_row_order_matches_input_order_per_task(run_multi):
    rows = {"gsm8k": [{"question": "q%d" % i, "answer": "5"}
                      for i in range(8)],
            "mmlu": [{"question": "m%d" % i, "answer": "B"}
                     for i in range(8)]}
    with fake_api.FakeAPI(fake_api.echo_user(), latency=0.01) as api:
        res = run_multi(api, inputs=rows, check=0)
    assert [r["input"]["question"] for r in res.task_rows("gsm8k")] == \
        ["q%d" % i for i in range(8)]
    assert [r["input"]["question"] for r in res.task_rows("mmlu")] == \
        ["m%d" % i for i in range(8)]


# ---------------------------------------------------------------------------
# Spec: "The stdout summary now includes a `tasks` object keyed by executed
#        task name"
# Context: Summary And Scheduling.  Stdout is still exactly one JSON object.
# ---------------------------------------------------------------------------
def test_stdout_is_still_a_single_json_object(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, inputs=ROWS, check=0)
    parsed = json.loads(res.stdout.strip())
    assert parsed["tasks"]["gsm8k"]["total"] == 3


# ---------------------------------------------------------------------------
# Spec: "include only tasks that actually ran"
# Context: Summary And Scheduling.  AMBIGUITIES T43 — a Part 1 single-task
# config reports its one task under `tasks` too.
# ---------------------------------------------------------------------------
def test_single_task_config_reports_a_tasks_object(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, {"name": "gsm8k_solve"}, check=0)
    assert res.summary["tasks"] == {
        "gsm8k_solve": {"total": 1, "passed": 1, "failed": 0,
                        "total_api_calls": 1, "total_solutions": 1,
                        "avg_solutions_per_input": 1.0}}
