"""Part 3: the list output format, `result` counters and per-attempt `meta`."""

import fake_api

from test_icl_config import icl, inline_setup


A_B = [inline_setup("chain_of_thought", "A-ex"), inline_setup("direct", "B-ex")]

SAMPLE = {"scheme": "sample", "temperature": 0.7}
REJECTION = {"scheme": "rejection", "temperature": 0.7}

META_KEYS = {"model", "prompt_tokens", "completion_tokens", "total_tokens",
             "latency_ms", "finish_reason", "icl_setup", "evaluation_passed"}


# ---------------------------------------------------------------------------
# Spec: "`output` becomes a list of objects, each containing the task's
#        `output_field` plus `icl_setup`"
# Context: Output Changes.
# ---------------------------------------------------------------------------
def test_output_is_a_list_of_output_field_plus_icl_setup(run_task):
    task = {"icl": icl(A_B, strategy="round_robin"), "num_solutions": 2,
            "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.sequence(["15 + 27 = 42\n#### 42",
                                             "#### 42"])) as api:
        res = run_task(api, task=task,
                       rows=[{"question": "What is 15 + 27?", "answer": "42"}],
                       check=0)
    assert res.rows[0]["output"] == [
        {"solution": "15 + 27 = 42\n#### 42", "icl_setup": "chain_of_thought"},
        {"solution": "#### 42", "icl_setup": "direct"},
    ]


# ---------------------------------------------------------------------------
# Spec: "`icl_setup` is the chosen setup name, or `null` when no ICL is
#        configured"
# Context: Output Changes.
# ---------------------------------------------------------------------------
def test_icl_setup_is_null_without_icl(run_task):
    task = {"num_solutions": 2, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    row = res.rows[0]
    assert [o["icl_setup"] for o in row["output"]] == [None, None]
    assert [m["icl_setup"] for m in row["meta"]] == [None, None]


# ---------------------------------------------------------------------------
# Spec: "`input`: {"question": "What is 15 + 27?", "answer": "42"}"
# Context: Output Changes.  The row's `input` is still the source row.
# ---------------------------------------------------------------------------
def test_input_is_still_the_source_row(run_task):
    rows = [{"question": "What is 15 + 27?", "answer": "42"}]
    task = {"num_solutions": 2, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 42")) as api:
        res = run_task(api, task=task, rows=rows, check=0)
    assert res.rows[0]["input"] == rows[0]


# ---------------------------------------------------------------------------
# Spec: '"result": {"passed": 2, "failed": 5, "attempts": 7}'
# Context: Output Changes; T47.  The list format's `result` has exactly these
# three keys.
# ---------------------------------------------------------------------------
def test_result_has_exactly_passed_failed_attempts(run_task):
    task = {"num_solutions": 2, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert set(res.rows[0]["result"]) == {"passed", "failed", "attempts"}


# ---------------------------------------------------------------------------
# Spec: "`result.passed` is the count of passing solutions" /
#       "`result.failed` is the count of failed attempts" /
#       "`result.attempts` is the total number of generation attempts for the
#        row"
# Context: Output Changes.
# ---------------------------------------------------------------------------
def test_result_counters(run_task):
    task = {"num_solutions": 4, "generation": SAMPLE}
    script = ["#### 5", "#### 9", "#### 5", "#### 9"]
    with fake_api.FakeAPI(fake_api.sequence(script)) as api:
        res = run_task(api, task=task, check=0)
    assert res.rows[0]["result"] == {"passed": 2, "failed": 2, "attempts": 4}


# ---------------------------------------------------------------------------
# Spec: "`meta` is a list with one entry per attempt"
# Context: Output Changes.
# ---------------------------------------------------------------------------
def test_meta_is_a_list_with_one_entry_per_attempt(run_task):
    task = {"num_solutions": 3, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    row = res.rows[0]
    assert isinstance(row["meta"], list)
    assert len(row["meta"]) == row["result"]["attempts"] == 3


# ---------------------------------------------------------------------------
# Spec: '{"model": "gpt-4", "prompt_tokens": 80, "completion_tokens": 15,
#         "total_tokens": 95, "latency_ms": 200, "finish_reason": "stop",
#         "icl_setup": "chain_of_thought", "evaluation_passed": true}'
# Context: Output Changes.  A metadata entry keeps the Part 1 fields and gains
# two.
# ---------------------------------------------------------------------------
def test_metadata_entry_fields(run_task):
    task = {"icl": icl(A_B), "num_solutions": 1}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    meta = res.rows[0]["meta"][0]
    assert set(meta) == META_KEYS
    assert meta["model"] == "gpt-4"
    assert meta["prompt_tokens"] == 45
    assert meta["completion_tokens"] == 120
    assert meta["total_tokens"] == 165
    assert meta["finish_reason"] == "stop"
    assert isinstance(meta["latency_ms"], int)


# ---------------------------------------------------------------------------
# Spec: "each metadata entry includes `icl_setup` and `evaluation_passed`"
# Context: Output Changes.  Per-attempt setup names and verdicts.
# ---------------------------------------------------------------------------
def test_metadata_records_setup_and_verdict_per_attempt(run_task):
    task = {"icl": icl(A_B, strategy="round_robin"), "num_solutions": 3,
            "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.sequence(["#### 5", "#### 9", "#### 5"])) \
            as api:
        res = run_task(api, task=task, check=0)
    metas = res.rows[0]["meta"]
    assert [m["icl_setup"] for m in metas] == \
        ["chain_of_thought", "direct", "chain_of_thought"]
    assert [m["evaluation_passed"] for m in metas] == [True, False, True]


# ---------------------------------------------------------------------------
# Spec: "if evaluation is omitted in list format, `evaluation_passed` is `null`
#        for each metadata entry, `result.passed` is the number of emitted
#        outputs, and `result.failed` is the number of attempts that produced
#        no output"
# Context: Output Changes.
# ---------------------------------------------------------------------------
def test_list_format_without_evaluation(run_task):
    task = {"evaluation": None, "num_solutions": 3, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    row = res.rows[0]
    assert [m["evaluation_passed"] for m in row["meta"]] == [None, None, None]
    assert row["result"] == {"passed": 3, "failed": 0, "attempts": 3}


# ---------------------------------------------------------------------------
# Spec: "`result.failed` is the number of attempts that produced no output"
# Context: Output Changes (evaluation omitted).  A dead attempt counts failed.
# ---------------------------------------------------------------------------
def test_without_evaluation_a_dead_attempt_counts_as_failed(run_task):
    task = {"evaluation": None, "num_solutions": 3, "generation": SAMPLE}
    # The first logical attempt burns its three retries on 5xx responses.
    with fake_api.FakeAPI(fake_api.fail_times(3, "#### 5")) as api:
        res = run_task(api, task=task, check=0)
    row = res.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}


# ---------------------------------------------------------------------------
# Spec: "each metadata entry includes ... `evaluation_passed`"
# Context: Output Changes; T52.  With an evaluation configured, an attempt that
# produced nothing did not pass.
# ---------------------------------------------------------------------------
def test_dead_attempt_evaluation_passed_is_false(run_task):
    task = {"num_solutions": 2, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.fail_times(3, "#### 5")) as api:
        res = run_task(api, task=task, check=0)
    metas = res.rows[0]["meta"]
    assert [m["evaluation_passed"] for m in metas] == [False, True]


# ---------------------------------------------------------------------------
# Spec: "when `num_solutions == 1` and no ICL is configured, keep the Part 1
#        output format"
# Context: Output Changes.
# ---------------------------------------------------------------------------
def test_part_1_format_is_kept_without_icl_and_one_solution(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, check=0)
    row = res.rows[0]
    assert row["output"] == {"solution": "#### 5"}
    assert row["result"] == {"passed": True, "extracted_answer": "5",
                             "attempts": 1}
    assert isinstance(row["meta"], dict)


# ---------------------------------------------------------------------------
# Spec: "when ICL is configured, use the list format even if
#        `num_solutions == 1`" / "with `num_solutions: 1` and ICL enabled,
#        `output` is still a list ... `meta` is also a list and includes
#        `evaluation_passed`"
# Context: Output Changes; Examples (single-solution ICL run).
# ---------------------------------------------------------------------------
def test_single_solution_icl_run_uses_the_list_format(run_task):
    task = {"icl": icl(A_B)}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    row = res.rows[0]
    assert row["output"] == [{"solution": "#### 5",
                              "icl_setup": "chain_of_thought"}]
    assert row["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert isinstance(row["meta"], list) and len(row["meta"]) == 1
    assert row["meta"][0]["evaluation_passed"] is True
    assert row["meta"][0]["icl_setup"] == "chain_of_thought"


# ---------------------------------------------------------------------------
# Spec: "If ICL is configured or `num_solutions > 1`, the per-row output format
#        changes"
# Context: Output Changes.  `num_solutions > 1` alone is enough.
# ---------------------------------------------------------------------------
def test_num_solutions_above_one_switches_the_format(run_task):
    task = {"num_solutions": 2, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    row = res.rows[0]
    assert isinstance(row["output"], list)
    assert isinstance(row["meta"], list)


# ---------------------------------------------------------------------------
# Spec: "write only those two passing outputs"
# Context: Output Changes; T61.  A row that collected nothing writes an empty
# list, not `null`.
# ---------------------------------------------------------------------------
def test_row_with_no_collected_solutions_writes_an_empty_list(run_task):
    task = {"num_solutions": 2, "generation": dict(REJECTION, max_attempts=2)}
    with fake_api.FakeAPI(fake_api.always("#### 9")) as api:
        res = run_task(api, task=task, check=0)
    row = res.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}


# ---------------------------------------------------------------------------
# Spec: "`output` becomes a list of objects, each containing the task's
#        `output_field`"
# Context: Output Changes.  The task's own `output_field` name is used.
# ---------------------------------------------------------------------------
def test_output_field_name_is_the_tasks_own(run_task):
    task = {"output_field": "answer_text", "num_solutions": 2,
            "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert set(res.rows[0]["output"][0]) == {"answer_text", "icl_setup"}


# ---------------------------------------------------------------------------
# Spec: "Existing behavior from earlier parts is unchanged unless stated here."
# Context: Output Changes.  One output row per input row, in input order.
# ---------------------------------------------------------------------------
def test_one_row_per_input_in_order(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(4)]
    task = {"num_solutions": 2, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, rows=rows, check=0)
    assert [r["input"]["question"] for r in res.rows] == \
        ["q0", "q1", "q2", "q3"]
