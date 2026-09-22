"""Per-row output records: input echo, output field, result and meta."""

from __future__ import annotations

import json

from conftest import base_task
from fake_api import FakeAPI, Reply, always, by_question, sequence


# Spec: "Write one JSON object per input row, in the same order as the input."
# Context: Output.
def test_one_object_per_row_in_input_order(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=8, delay=0.05) as api:
        config = write_config(base_task(api.url))
        rows = [{"question": f"q{i}", "answer": "5"} for i in range(12)]
        data = write_input(rows)
        result = run_cli(config, data)
    assert [row["input"]["question"] for row in result.rows] == [
        f"q{i}" for i in range(12)
    ]


# Spec: "concurrent execution must not cause a later input row to consume the
# response intended for an earlier row."
# Context: Throughput; each row must keep its own response.
def test_responses_are_paired_with_their_own_row(write_config, write_input, run_cli):
    rows = [{"question": f"q{i}", "answer": str(i)} for i in range(12)]
    mapping = {f"q{i}": Reply(content=f"answer is {i}") for i in range(12)}
    with FakeAPI(responder=by_question(mapping), slots=8, delay=0.05) as api:
        config = write_config(base_task(api.url))
        data = write_input(rows)
        result = run_cli(config, data)
    for index, row in enumerate(result.rows):
        assert row["output"]["solution"] == f"answer is {index}"
        assert row["result"]["passed"] is True


# Spec: "input is the original row, unchanged"
# Context: Output rules.
def test_input_is_echoed_unchanged(write_config, write_input, run_cli):
    original = {"question": "q", "answer": "5", "extra": {"nested": [1, 2]}, "id": 7}
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([original])
        result = run_cli(config, data)
    assert result.rows[0]["input"] == original


# Spec: "output is an object with one key named by output_field"
# Context: Output rules.
def test_output_key_is_the_configured_output_field(write_config, write_input, run_cli):
    with FakeAPI(responder=always("text here")) as api:
        task = base_task(api.url)
        task["output_field"] = "completion"
        task.pop("evaluation")
        config = write_config(task)
        data = write_input([{"question": "q"}])
        result = run_cli(config, data)
    assert result.rows[0]["output"] == {"completion": "text here"}


# Spec: "result.passed is true for a passing evaluation"
# Context: Output rules.
def test_passed_true_for_passing_evaluation(write_config, write_input, run_cli):
    with FakeAPI(responder=always("2 + 3 = 5\n#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    assert result.rows[0]["result"] == {
        "passed": True,
        "extracted_answer": "5",
        "attempts": 1,
    }


# Spec: "result.passed is ... false for a failing evaluation"
# Context: Output rules.
def test_passed_false_for_failing_evaluation(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 9")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    row = result.rows[0]
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] == "9"
    assert row["output"] == {"solution": "#### 9"}


# Spec: "if evaluation is omitted for greedy or sample, result.passed must be
# null"
# Context: Configuration / validation rules.
def test_passed_null_without_evaluation(write_config, write_input, run_cli):
    with FakeAPI(responder=always("some text")) as api:
        task = base_task(api.url)
        task.pop("evaluation")
        config = write_config(task)
        data = write_input([{"question": "q"}])
        result = run_cli(config, data)
    assert result.rows[0]["result"]["passed"] is None
    assert result.rows[0]["result"]["extracted_answer"] is None


# Spec: "result.attempts is ... 1 for greedy and sample"
# Context: Output rules.
def test_attempts_is_one_for_sample(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url)
        task["generation"] = {"scheme": "sample", "temperature": 0.8}
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    assert result.rows[0]["result"]["attempts"] == 1


# Spec: "meta is a single metadata object for one-attempt rows"
# Context: Output rules; meta fields per the example.
def test_meta_object_for_single_attempt(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), delay=0.05) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    meta = result.rows[0]["meta"]
    assert set(meta) == {
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
    }
    assert meta["model"] == "gpt-4"
    assert meta["finish_reason"] == "stop"


# Spec: "meta.latency_ms is wall-clock latency for that API call"
# Context: Output rules.
def test_latency_ms_reflects_call_duration(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), delay=0.25) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    latency = result.rows[0]["meta"]["latency_ms"]
    assert isinstance(latency, int)
    assert 200 <= latency < 5000


# Spec: the greedy example's exact output row.
# Context: Examples.
def test_greedy_example_row(write_config, write_input, run_cli):
    task = {
        "name": "math_solve",
        "api_url": None,
        "model": "gpt-4",
        "rpm": 60,
        "prompt": {
            "system": "Solve the math problem. Final answer after ####.",
            "user": "{question}",
        },
        "generation": {"scheme": "greedy", "max_tokens": 256},
        "evaluation": {
            "type": "exact_match",
            "answer_field": "answer",
            "extract": "last_number",
        },
        "output_field": "solution",
    }
    reply = Reply(content="2 + 3 = 5\n#### 5", prompt_tokens=30, completion_tokens=10)
    with FakeAPI(responder=sequence([reply])) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "What is 2 + 3?", "answer": "5"}])
        result = run_cli(config, data)
    row = result.rows[0]
    assert row["input"] == {"question": "What is 2 + 3?", "answer": "5"}
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}
    assert row["meta"]["model"] == "gpt-4"
    assert row["meta"]["prompt_tokens"] == 30
    assert row["meta"]["completion_tokens"] == 10
    assert row["meta"]["total_tokens"] == 40
    assert row["meta"]["finish_reason"] == "stop"


# Spec: output is JSONL — one JSON object per line, in order.
# Context: Output.
def test_output_file_is_jsonl(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(3)])
        result = run_cli(config, data)
    lines = result.output_path.read_text().splitlines()
    assert len(lines) == 3
    assert all(isinstance(json.loads(line), dict) for line in lines)


# Spec: "output is null" when the row produced no usable response, and
# "meta" then has no per-call data to report (see AMBIGUITIES T2, T3).
# Context: API Contract / Output rules.
def test_failed_row_shape(write_config, write_input, run_cli):
    with FakeAPI(responder=always("", status=500)) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"] == {"passed": False, "extracted_answer": None, "attempts": 1}
    assert row["meta"] is None


def test_failed_row_without_evaluation_has_null_verdict(write_config, write_input, run_cli):
    with FakeAPI(responder=always("", status=500)) as api:
        task = base_task(api.url)
        task.pop("evaluation")
        config = write_config(task)
        data = write_input([{"question": "q"}])
        result = run_cli(config, data)
    assert result.rows[0]["result"]["passed"] is None
    assert result.summary["failed"] == 1
    assert result.summary["passed"] == 0
