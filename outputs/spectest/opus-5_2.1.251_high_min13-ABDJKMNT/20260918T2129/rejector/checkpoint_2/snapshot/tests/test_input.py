"""JSONL input handling: ordering, row echoing, and input errors."""

from __future__ import annotations

from fake_server import FakeAPIServer, always, echo_user
from conftest import base_config


# Spec: "The input file is JSONL with one object per line."
# and "Write one JSON object per input row, in the same order as the input."
def test_rows_are_written_in_input_order(write_config, write_input, run_cli):
    questions = [f"q{i}" for i in range(12)]
    with FakeAPIServer(echo_user()) as api:
        config_map = base_config(api.url)
        config_map["task"]["evaluation"] = {"type": "contains", "answer_field": "answer"}
        config = write_config(config_map)
        rows = write_input([{"question": q, "answer": q} for q in questions])
        result = run_cli(config, rows)
    assert [row["input"]["question"] for row in result.rows] == questions
    assert [row["output"]["solution"] for row in result.rows] == questions


# Spec: "input is the original row, unchanged"
def test_input_row_is_echoed_unchanged(write_config, write_input, run_cli):
    row = {"question": "What is 2 + 3?", "answer": "5", "id": 17, "tags": ["math", "easy"]}
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([row]))
    assert result.rows[0]["input"] == row


# Spec: "one JSON object per input row" - one output line per input line
def test_one_output_line_per_input_row(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": f"q{i}", "answer": "5"} for i in range(5)])
        result = run_cli(config, rows)
    assert len(result.rows) == 5


# Spec: "1: configuration or input error" - a malformed JSONL line is an error
def test_malformed_jsonl_line_exits_1(write_config, write_input, run_cli):
    config = write_config(base_config("http://127.0.0.1:1"))
    rows = write_input(['{"question": "q", "answer": "5"}', "{not json"])
    result = run_cli(config, rows)
    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: "one object per line" - a non-object JSON line is an input error
def test_non_object_jsonl_line_exits_1(write_config, write_input, run_cli):
    config = write_config(base_config("http://127.0.0.1:1"))
    rows = write_input(["[1, 2, 3]"])
    result = run_cli(config, rows)
    assert result.returncode == 1


# Spec: "total: input row count" - an empty input yields an empty result set
def test_empty_input_produces_empty_output_and_zero_total(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([]))
    assert result.returncode == 0
    assert result.rows == []
    assert result.summary["total"] == 0
    assert result.summary["total_api_calls"] == 0


# Spec: blank lines carry no object and are skipped rather than failing
def test_blank_lines_are_ignored(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input(['{"question": "q", "answer": "5"}', "", '{"question": "q2", "answer": "5"}'])
        result = run_cli(config, rows)
    assert result.returncode == 0
    assert len(result.rows) == 2
