"""Per-row output shape, ordering, and rejection-sampling behaviour."""

import json

import pytest

import fake_api


# ---------------------------------------------------------------------------
# Spec: "Write one JSON object per input row, in the same order as the input."
# Context: Output.  Concurrency must not reorder or drop rows.
# ---------------------------------------------------------------------------
def test_one_row_per_input_row_in_input_order(run_task):
    rows = [{"question": "q%d" % i, "answer": str(i)} for i in range(12)]
    with fake_api.FakeAPI(fake_api.echo_user(), latency=0.02) as api:
        res = run_task(api, task={"evaluation": None}, rows=rows, check=0)
    assert len(res.rows) == 12
    assert [r["input"]["question"] for r in res.rows] == \
           ["q%d" % i for i in range(12)]
    # each row's response corresponds to its own prompt
    assert [r["output"]["solution"] for r in res.rows] == \
           ["q%d" % i for i in range(12)]


# ---------------------------------------------------------------------------
# Spec: "Write one JSON object per input row" — JSONL, one line each.
# Context: Output.
# ---------------------------------------------------------------------------
def test_output_is_one_json_object_per_line(run_task, workdir):
    rows = [{"question": "a", "answer": "1"}, {"question": "b", "answer": "2"}]
    with fake_api.FakeAPI(fake_api.always("#### 1")) as api:
        run_task(api, rows=rows, check=0)
    lines = [l for l in (workdir / "results.jsonl").read_text().splitlines() if l]
    assert len(lines) == 2
    for line in lines:
        assert isinstance(json.loads(line), dict)


# ---------------------------------------------------------------------------
# Spec: "input is the original row, unchanged"
# Context: Output.  Extra fields are preserved verbatim.
# ---------------------------------------------------------------------------
def test_input_row_is_echoed_unchanged(run_task):
    row = {"question": "What is 2 + 3?", "answer": "5",
           "id": 17, "meta": {"src": "gsm8k"}, "tags": ["a", "b"]}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, rows=[row], check=0)
    assert res.rows[0]["input"] == row


# ---------------------------------------------------------------------------
# Spec: "output is an object with one key named by output_field"
# Context: Output.
# ---------------------------------------------------------------------------
def test_output_object_is_keyed_by_output_field(run_task):
    with fake_api.FakeAPI(fake_api.always("some text")) as api:
        res = run_task(api, task={"output_field": "completion",
                                  "evaluation": None},
                       rows=[{"question": "q"}], check=0)
    assert res.rows[0]["output"] == {"completion": "some text"}


# ---------------------------------------------------------------------------
# Spec: "result.passed is true for a passing evaluation, false for a failing
#        evaluation, and null when no evaluation is configured"
# Context: Output.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("content,expected", [("#### 5", True), ("#### 6", False)])
def test_passed_reflects_evaluation_outcome(run_task, content, expected):
    with fake_api.FakeAPI(fake_api.always(content)) as api:
        res = run_task(api, task={"evaluation": {"type": "exact_match",
                                                 "answer_field": "answer",
                                                 "extract": "last_number"}},
                       rows=[{"question": "q", "answer": "5"}], check=0)
    assert res.rows[0]["result"]["passed"] is expected


# ---------------------------------------------------------------------------
# Spec: "result.passed is ... null when no evaluation is configured"
# Context: Output.  extracted_answer is null in that case too.
# ---------------------------------------------------------------------------
def test_no_evaluation_gives_null_passed_and_null_extracted(run_task):
    with fake_api.FakeAPI(fake_api.always("anything")) as api:
        res = run_task(api, task={"evaluation": None},
                       rows=[{"question": "q"}], check=0)
    assert res.rows[0]["result"]["passed"] is None
    assert res.rows[0]["result"]["extracted_answer"] is None


# ---------------------------------------------------------------------------
# Spec: "output is an object ...; if all attempts fail, output is null"
#       + "failed: rows where result.passed is false or output is null"
# Context: AMBIGUITIES T16 — a greedy row that fails evaluation keeps its text.
# ---------------------------------------------------------------------------
def test_greedy_keeps_output_when_evaluation_fails(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 6")) as api:
        res = run_task(api, task={"evaluation": {"type": "exact_match",
                                                 "answer_field": "answer",
                                                 "extract": "last_number"}},
                       rows=[{"question": "q", "answer": "5"}], check=0)
    assert res.rows[0]["output"] == {"solution": "#### 6"}
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "result.attempts ... 1 for greedy and sample"
# Context: Output.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gen", [
    {"scheme": "greedy"},
    {"scheme": "sample", "temperature": 0.7},
])
def test_attempts_is_one_for_greedy_and_sample(run_task, gen):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task={"generation": gen}, check=0)
    assert res.rows[0]["result"]["attempts"] == 1


# ---------------------------------------------------------------------------
# Spec: "meta is a single metadata object for one-attempt rows"
# Context: Output.  Greedy rows carry a dict, not a list, with all six fields.
# ---------------------------------------------------------------------------
def test_meta_is_a_single_object_for_one_attempt_rows(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, check=0)
    meta = res.rows[0]["meta"]
    assert isinstance(meta, dict)
    assert set(meta) == {"model", "prompt_tokens", "completion_tokens",
                         "total_tokens", "latency_ms", "finish_reason"}


# ---------------------------------------------------------------------------
# Spec: "meta.latency_ms is wall-clock latency for that API call"
# Context: Output.  A server that sleeps ~150ms must report at least that.
# ---------------------------------------------------------------------------
def test_latency_ms_measures_the_api_call(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5"), latency=0.15) as api:
        res = run_task(api, check=0)
    latency = res.rows[0]["meta"]["latency_ms"]
    assert isinstance(latency, (int, float))
    assert 140 <= latency < 5000


# ---------------------------------------------------------------------------
# Spec: the worked greedy output row from the Examples section.
# Context: Examples.  Full-shape assertion of every documented key.
# ---------------------------------------------------------------------------
def test_greedy_example_row_shape(run_task):
    responder = fake_api.always("2 + 3 = 5\n#### 5", prompt_tokens=30,
                                completion_tokens=10)
    with fake_api.FakeAPI(responder) as api:
        res = run_task(api,
                       task={"generation": {"scheme": "greedy",
                                            "max_tokens": 256},
                             "evaluation": {"type": "exact_match",
                                            "answer_field": "answer",
                                            "extract": "last_number"},
                             "output_field": "solution"},
                       rows=[{"question": "What is 2 + 3?", "answer": "5"}],
                       check=0)
    row = res.rows[0]
    assert set(row) == {"input", "output", "result", "meta"}
    assert row["input"] == {"question": "What is 2 + 3?", "answer": "5"}
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["result"] == {"passed": True, "extracted_answer": "5",
                             "attempts": 1}
    assert row["meta"]["model"] == "gpt-4"
    assert row["meta"]["prompt_tokens"] == 30
    assert row["meta"]["completion_tokens"] == 10
    assert row["meta"]["total_tokens"] == 40
    assert row["meta"]["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# Spec: "rejection: ... make up to n attempts and keep the first passing
#        response"  +  "Rejection example with n: 3: if the first two
#        responses fail evaluation and the third passes, the output row
#        records attempts: 3, keeps the third response as output, and includes
#        three metadata entries."
# Context: Generation behavior + Examples.
# ---------------------------------------------------------------------------
def test_rejection_keeps_first_passing_response(run_task):
    script = fake_api.sequence(["#### 1", "#### 2", "#### 5"])
    with fake_api.FakeAPI(script) as api:
        res = run_task(api,
                       task={"generation": {"scheme": "rejection",
                                            "temperature": 0.8, "n": 3},
                             "evaluation": {"type": "exact_match",
                                            "answer_field": "answer",
                                            "extract": "last_number"}},
                       rows=[{"question": "q", "answer": "5"}], check=0)
        assert api.call_count == 3
    row = res.rows[0]
    assert row["output"] == {"solution": "#### 5"}
    assert row["result"]["attempts"] == 3
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "5"
    assert isinstance(row["meta"], list) and len(row["meta"]) == 3


# ---------------------------------------------------------------------------
# Spec: "make up to n attempts and keep the first passing response"
# Context: Generation behavior.  Passing early stops further attempts.
# ---------------------------------------------------------------------------
def test_rejection_stops_at_first_pass(run_task):
    script = fake_api.sequence(["#### 9", "#### 5", "#### 5", "#### 5"])
    with fake_api.FakeAPI(script) as api:
        res = run_task(api,
                       task={"generation": {"scheme": "rejection",
                                            "temperature": 0.8, "n": 5},
                             "evaluation": {"type": "exact_match",
                                            "answer_field": "answer",
                                            "extract": "last_number"}},
                       rows=[{"question": "q", "answer": "5"}], check=0)
        assert api.call_count == 2
    assert res.rows[0]["result"]["attempts"] == 2
    assert len(res.rows[0]["meta"]) == 2


# ---------------------------------------------------------------------------
# Spec: "if all attempts fail, output null with "passed": false" and the
#       worked failure row with attempts: 5 and five metadata entries.
# Context: Generation behavior + Output.
# ---------------------------------------------------------------------------
def test_rejection_exhausted_emits_null_output(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 1")) as api:
        res = run_task(api,
                       task={"generation": {"scheme": "rejection",
                                            "temperature": 0.8, "n": 5},
                             "evaluation": {"type": "exact_match",
                                            "answer_field": "answer",
                                            "extract": "last_number"}},
                       rows=[{"question": "q", "answer": "42"}], check=0)
        assert api.call_count == 5
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"] == {"passed": False, "extracted_answer": None,
                             "attempts": 5}
    assert isinstance(row["meta"], list) and len(row["meta"]) == 5


# ---------------------------------------------------------------------------
# Spec: "result.attempts ... 1..n for rejection" +
#       "meta is a single metadata object for one-attempt rows"
# Context: AMBIGUITIES T2 — a rejection row that passes immediately is a
# one-attempt row and gets a bare meta object.
# ---------------------------------------------------------------------------
def test_rejection_passing_immediately_has_one_attempt(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api,
                       task={"generation": {"scheme": "rejection",
                                            "temperature": 0.8, "n": 4},
                             "evaluation": {"type": "exact_match",
                                            "answer_field": "answer",
                                            "extract": "last_number"}},
                       rows=[{"question": "q", "answer": "5"}], check=0)
        assert api.call_count == 1
    assert res.rows[0]["result"]["attempts"] == 1
    assert isinstance(res.rows[0]["meta"], dict)


# ---------------------------------------------------------------------------
# Spec: "After the third failure, treat that row as failed" inside rejection
# Context: AMBIGUITIES T15 — retry exhaustion on attempt 2 fails the row then
# and there, so attempts stops at 2 and no further attempts are made.
# ---------------------------------------------------------------------------
def test_rejection_row_fails_when_retries_exhaust_mid_attempt(run_task):
    script = fake_api.sequence(["#### 1", 500, 500, 500, "#### 5"])
    with fake_api.FakeAPI(script) as api:
        res = run_task(api,
                       task={"generation": {"scheme": "rejection",
                                            "temperature": 0.8, "n": 5},
                             "evaluation": {"type": "exact_match",
                                            "answer_field": "answer",
                                            "extract": "last_number"}},
                       rows=[{"question": "q", "answer": "5"}], check=0)
        assert api.call_count == 4          # 1 ok + 3 failed calls
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["attempts"] == 2
    assert res.summary["total_api_calls"] == 4


# ---------------------------------------------------------------------------
# Spec: "meta is a single metadata object for one-attempt rows; for rejection
#        sampling with multiple attempts it is a list"
# Context: Output.  Each attempt's meta is its own entry with its own usage.
# ---------------------------------------------------------------------------
def test_rejection_meta_entries_are_per_attempt(run_task):
    calls = {"i": 0}

    def responder(rec):
        calls["i"] += 1
        i = calls["i"]
        return 200, fake_api.completion("#### %d" % i, prompt_tokens=10 * i,
                                        completion_tokens=i)
    with fake_api.FakeAPI(responder) as api:
        res = run_task(api,
                       task={"generation": {"scheme": "rejection",
                                            "temperature": 0.8, "n": 3},
                             "evaluation": {"type": "exact_match",
                                            "answer_field": "answer",
                                            "extract": "last_number"}},
                       rows=[{"question": "q", "answer": "3"}], check=0)
    metas = res.rows[0]["meta"]
    assert [m["prompt_tokens"] for m in metas] == [10, 20, 30]
    assert [m["completion_tokens"] for m in metas] == [1, 2, 3]
