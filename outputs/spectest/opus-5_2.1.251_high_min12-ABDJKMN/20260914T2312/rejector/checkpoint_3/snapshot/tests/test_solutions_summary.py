"""Part 3: the per-task summary gains `total_solutions` and the average."""

import fake_api

from test_icl_config import icl, inline_setup


SAMPLE = {"scheme": "sample", "temperature": 0.7}
REJECTION = {"scheme": "rejection", "temperature": 0.7}

TWO_ROWS = [{"question": "q1", "answer": "5"}, {"question": "q2", "answer": "5"}]


# ---------------------------------------------------------------------------
# Spec: 'Per-task summary fields gain: {"total": 100, "total_solutions": 450,
#        "avg_solutions_per_input": 4.5, "total_api_calls": 850}'
# Context: Output Changes.  The new keys are present on the per-task object.
# ---------------------------------------------------------------------------
def test_per_task_summary_gains_the_new_fields(run_multi):
    tasks = {"gsm8k": {"generation": SAMPLE}, "mmlu": {"generation": SAMPLE}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, defaults={"num_solutions": 2}, tasks=tasks,
                        check=0)
    gsm8k = res.summary["tasks"]["gsm8k"]
    assert {"total", "total_solutions", "avg_solutions_per_input",
            "total_api_calls"} <= set(gsm8k)
    assert gsm8k["total"] == 1
    assert gsm8k["total_solutions"] == 2
    assert gsm8k["avg_solutions_per_input"] == 2.0
    assert gsm8k["total_api_calls"] == 2


# ---------------------------------------------------------------------------
# Spec: '"total_solutions": 450'
# Context: Output Changes.  Solutions are summed over the task's rows, which
# may differ per row.
# ---------------------------------------------------------------------------
def test_total_solutions_sums_over_rows(run_task):
    task = {"num_solutions": 2, "generation": dict(REJECTION, max_attempts=3)}
    script = {"q1": ["#### 5", "#### 5"],
              "q2": ["#### 5", "#### 9", "#### 9"]}
    with fake_api.FakeAPI(fake_api.per_prompt(script)) as api:
        res = run_task(api, task=task, rows=TWO_ROWS, check=0)
    task_summary = res.summary["tasks"]["gsm8k_solve"]
    assert task_summary["total"] == 2
    assert task_summary["total_solutions"] == 3
    assert task_summary["total_api_calls"] == 5


# ---------------------------------------------------------------------------
# Spec: '"avg_solutions_per_input": 4.5'
# Context: Output Changes.  `total_solutions / total`.
# ---------------------------------------------------------------------------
def test_avg_solutions_per_input(run_task):
    task = {"num_solutions": 2, "generation": dict(REJECTION, max_attempts=3)}
    script = {"q1": ["#### 5", "#### 5"],
              "q2": ["#### 5", "#### 9", "#### 9"]}
    with fake_api.FakeAPI(fake_api.per_prompt(script)) as api:
        res = run_task(api, task=task, rows=TWO_ROWS, check=0)
    assert res.summary["tasks"]["gsm8k_solve"]["avg_solutions_per_input"] == 1.5


# ---------------------------------------------------------------------------
# Spec: '"avg_solutions_per_input": 4.5'
# Context: Output Changes; T53.  A ratio that does not divide evenly is
# reported to two decimals.
# ---------------------------------------------------------------------------
def test_avg_solutions_per_input_rounds_to_two_decimals(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(1, 4)]
    task = {"num_solutions": 3, "generation": dict(REJECTION, max_attempts=3)}
    script = {"q1": ["#### 5", "#### 5", "#### 5"],
              "q2": ["#### 5", "#### 5", "#### 9"],
              "q3": ["#### 5", "#### 5", "#### 9"]}
    with fake_api.FakeAPI(fake_api.per_prompt(script)) as api:
        res = run_task(api, task=task, rows=rows, check=0)
    task_summary = res.summary["tasks"]["gsm8k_solve"]
    assert task_summary["total_solutions"] == 7
    assert task_summary["avg_solutions_per_input"] == 2.33


# ---------------------------------------------------------------------------
# Spec: "Per-task summary fields gain: ..."
# Context: Output Changes; T53.  The fields are unconditional: a plain
# single-solution task reports them too.
# ---------------------------------------------------------------------------
def test_new_summary_fields_exist_for_a_plain_task(run_multi):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, check=0)
    for name in ("gsm8k", "mmlu"):
        task_summary = res.summary["tasks"][name]
        assert task_summary["total_solutions"] == 1
        assert task_summary["avg_solutions_per_input"] == 1.0


# ---------------------------------------------------------------------------
# Spec: '{"tasks": {"gsm8k": {"total": 100, ...}}}'
# Context: Output Changes; T54.  `total`, `passed` and `failed` stay row
# counts: a row that collected at least one passing solution passed.
# ---------------------------------------------------------------------------
def test_passed_and_failed_stay_row_counts(run_task):
    task = {"num_solutions": 3, "generation": dict(REJECTION, max_attempts=2)}
    script = {"q1": ["#### 5", "#### 9"], "q2": ["#### 9", "#### 9"]}
    with fake_api.FakeAPI(fake_api.per_prompt(script)) as api:
        res = run_task(api, task=task, rows=TWO_ROWS, check=0)
    task_summary = res.summary["tasks"]["gsm8k_solve"]
    assert task_summary["total"] == 2
    assert task_summary["passed"] == 1
    assert task_summary["failed"] == 1
    assert task_summary["total_solutions"] == 1
    assert res.summary["passed"] == 1
    assert res.summary["failed"] == 1


# ---------------------------------------------------------------------------
# Spec: '"total_api_calls": 850'
# Context: Output Changes.  Every generation attempt, including ICL attempts
# that fail evaluation, is an API call.
# ---------------------------------------------------------------------------
def test_total_api_calls_counts_every_attempt(run_task):
    task = {"icl": icl([inline_setup("A", "A-ex"), inline_setup("B", "B-ex")],
                       strategy="round_robin"),
            "num_solutions": 4, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 9")) as api:
        res = run_task(api, task=task, check=0)
    assert api.call_count == 4
    assert res.summary["tasks"]["gsm8k_solve"]["total_api_calls"] == 4
    assert res.summary["total_api_calls"] == 4


# ---------------------------------------------------------------------------
# Spec: "Existing behavior from earlier parts is unchanged unless stated here."
# Context: Output Changes.  The Part 1/2 summary keys survive alongside the new
# ones.
# ---------------------------------------------------------------------------
def test_existing_summary_keys_survive(run_task):
    task = {"num_solutions": 2, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert {"total", "passed", "failed", "total_prompt_tokens",
            "total_completion_tokens", "total_api_calls", "elapsed_seconds",
            "throughput_rpm"} <= set(res.summary)
