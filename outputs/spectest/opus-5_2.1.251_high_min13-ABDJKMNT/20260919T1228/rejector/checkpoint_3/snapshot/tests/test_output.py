"""Per-row output shape: input/output/result/meta."""

from __future__ import annotations

from conftest import make_config


# Spec: the per-row shape has exactly the keys input, output, result, meta.
def test_row_has_the_documented_top_level_keys(servers, run_cli):
    server = servers(contents=["#### 8"])
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "8"}])
    assert list(result.rows[0]) == ["input", "output", "result", "meta"]


# Spec: the greedy example -- input echoed, output keyed by output_field,
# result passing with the extracted answer, one attempt, one meta object.
def test_greedy_example_row(servers, run_cli):
    server = servers(contents=["2 + 3 = 5\n#### 5"], prompt_tokens=30, completion_tokens=10)
    config = make_config(
        server.url,
        name="math_solve",
        prompt={"system": "Solve the math problem. Final answer after ####.", "user": "{question}"},
        generation={"scheme": "greedy", "max_tokens": 256},
    )
    result = run_cli(config, [{"question": "What is 2 + 3?", "answer": "5"}])
    row = result.rows[0]
    assert row["input"] == {"question": "What is 2 + 3?", "answer": "5"}
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}
    assert row["meta"]["model"] == "gpt-4"


# Spec: "output is an object with one key named by output_field".
def test_output_key_follows_output_field(servers, run_cli):
    server = servers(contents=["#### 8"])
    config = make_config(server.url, output_field="completion")
    result = run_cli(config, [{"question": "q", "answer": "8"}])
    assert result.rows[0]["output"] == {"completion": "#### 8"}


# Spec: "result.passed is true for a passing evaluation".
def test_passed_true_for_passing_evaluation(servers, run_cli):
    server = servers(contents=["#### 8"])
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "8"}])
    assert result.rows[0]["result"]["passed"] is True


# Spec: "result.passed is ... false for a failing evaluation" -- and the output
# of a failing greedy row is still recorded.
def test_passed_false_keeps_the_output(servers, run_cli):
    server = servers(contents=["#### 9"])
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "8"}])
    row = result.rows[0]
    assert row["result"]["passed"] is False
    assert row["output"] == {"solution": "#### 9"}
    assert row["result"]["extracted_answer"] == "9"


# Spec: "result.extracted_answer is ... null when there is no evaluation".
def test_extracted_answer_is_null_without_evaluation(server, run_cli):
    config = make_config(server.url, evaluation=None)
    result = run_cli(config, [{"question": "q"}])
    assert result.rows[0]["result"]["extracted_answer"] is None


# Spec: "result.extracted_answer is ... null when there is ... no output".
def test_extracted_answer_is_null_when_output_is_null(servers, run_cli):
    server = servers(fail_calls=set(range(50)))
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "8"}])
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"]["extracted_answer"] is None


# Spec: "result.attempts is ... 1 for greedy and sample".
def test_attempts_is_one_for_sample(servers, run_cli):
    server = servers(contents=["#### 8"])
    config = make_config(server.url, generation={"scheme": "sample", "temperature": 0.7})
    result = run_cli(config, [{"question": "q", "answer": "8"}])
    assert result.rows[0]["result"]["attempts"] == 1


# Spec: "meta is a single metadata object for one-attempt rows" with the
# documented fields.
def test_meta_object_fields(servers, run_cli):
    server = servers(contents=["#### 8"], prompt_tokens=45, completion_tokens=120)
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "8"}])
    meta = result.rows[0]["meta"]
    assert set(meta) == {
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
    }
    assert meta["prompt_tokens"] == 45
    assert meta["completion_tokens"] == 120
    assert meta["total_tokens"] == 165


# Spec: "meta.latency_ms is wall-clock latency for that API call".
def test_latency_ms_reflects_call_duration(servers, run_cli):
    server = servers(contents=["#### 8"], service_time=0.3)
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "8"}])
    assert result.rows[0]["meta"]["latency_ms"] >= 300


# Spec: "rejection: ... make up to n attempts and keep the first passing
# response" -- the example where the first two fail and the third passes.
def test_rejection_keeps_the_first_passing_response(servers, run_cli):
    server = servers(contents=["#### 1", "#### 2", "#### 8", "#### 9"], workers=1)
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 3}
    )
    result = run_cli(config, [{"question": "q", "answer": "8"}])
    row = result.rows[0]
    assert row["output"] == {"solution": "#### 8"}
    assert row["result"]["passed"] is True
    assert row["result"]["attempts"] == 3
    assert row["result"]["extracted_answer"] == "8"


# Spec: "for rejection sampling with multiple attempts it [meta] is a list with
# one metadata object per attempt".
def test_rejection_meta_is_a_list_per_attempt(servers, run_cli):
    server = servers(contents=["#### 1", "#### 2", "#### 8"], workers=1)
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 3}
    )
    result = run_cli(config, [{"question": "q", "answer": "8"}])
    meta = result.rows[0]["meta"]
    assert isinstance(meta, list)
    assert len(meta) == 3
    assert all(entry["model"] == "gpt-4" for entry in meta)


# Spec: "meta is a single metadata object for one-attempt rows" -- including a
# rejection row that passed on its first attempt.
def test_rejection_single_attempt_meta_is_an_object(servers, run_cli):
    server = servers(contents=["#### 8"])
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 3}
    )
    result = run_cli(config, [{"question": "q", "answer": "8"}])
    row = result.rows[0]
    assert row["result"]["attempts"] == 1
    assert isinstance(row["meta"], dict)


# Spec: "if all attempts fail, output null with passed: false" -- the
# exhausted-rejection example with n=5.
def test_rejection_exhausted_row(servers, run_cli):
    server = servers(contents=["#### 1"], workers=1)
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 5}
    )
    result = run_cli(config, [{"question": "q", "answer": "42"}])
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"] == {"passed": False, "extracted_answer": None, "attempts": 5}
    assert isinstance(row["meta"], list) and len(row["meta"]) == 5
    assert server.call_count == 5


# Spec: "rejection: ... keep the first passing response" -- no further
# attempts are made once one passes.
def test_rejection_stops_after_a_pass(servers, run_cli):
    server = servers(contents=["#### 8"])
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 5}
    )
    run_cli(config, [{"question": "q", "answer": "8"}])
    assert server.call_count == 1


# Spec: "rejection: temperature must be > 0" -- every attempt uses it.
def test_rejection_attempts_use_the_configured_temperature(servers, run_cli):
    server = servers(contents=["#### 1"], workers=1)
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.65, "n": 3}
    )
    run_cli(config, [{"question": "q", "answer": "42"}])
    assert [payload["temperature"] for payload in server.payloads] == [0.65] * 3


# Spec: a row whose API calls all failed has no metadata to report. (T5)
def test_failed_row_meta_is_null(servers, run_cli):
    server = servers(fail_calls=set(range(50)))
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "8"}])
    assert result.rows[0]["meta"] is None


# Spec: "Write one JSON object per input row" -- one line each, in order.
def test_one_line_per_row(servers, run_cli):
    server = servers(contents=["#### 8"])
    rows = [{"question": f"q{i}", "answer": "8"} for i in range(5)]
    result = run_cli(make_config(server.url), rows)
    lines = result.output_path.read_text().splitlines()
    assert len(lines) == 5
