"""Input file handling and prompt template rendering."""

from __future__ import annotations

import subprocess
import sys

import yaml

from conftest import PROJECT_ROOT, make_config


# Spec: "The input file is JSONL with one object per line" and "Write one JSON
# object per input row, in the same order as the input".
def test_rows_are_processed_in_input_order(server, run_cli):
    rows = [{"question": f"q{i}", "answer": "42"} for i in range(8)]
    result = run_cli(make_config(server.url), rows)
    assert [row["input"]["question"] for row in result.rows] == [
        f"q{i}" for i in range(8)
    ]


# Spec: "prompt.system and prompt.user use {field} placeholders resolved from
# each input row".
def test_placeholders_are_rendered_from_the_row(server, run_cli):
    config = make_config(
        server.url,
        prompt={"system": "You grade {subject} answers.", "user": "Q: {question}"},
    )
    run_cli(config, [{"question": "2+3?", "subject": "math", "answer": "42"}])
    messages = server.payloads[0]["messages"]
    assert messages[0]["content"] == "You grade math answers."
    assert messages[1]["content"] == "Q: 2+3?"


# Spec: "If a placeholder references a missing field, exit with code 1 and
# print an error to stderr naming the row index and missing field" -- with the
# spec's own example: template {question}, row 0 is {"text": "hello"}.
def test_missing_placeholder_field_exits_1_naming_row_and_field(server, run_cli):
    result = run_cli(make_config(server.url), [{"text": "hello"}])
    assert result.exit_code == 1
    assert "0" in result.stderr
    assert "question" in result.stderr


# Spec: the error names the offending row index, not always row 0.
def test_missing_field_error_names_the_offending_row_index(server, run_cli):
    rows = [{"question": "ok", "answer": "42"}, {"answer": "42"}]
    result = run_cli(make_config(server.url), rows)
    assert result.exit_code == 1
    assert "1" in result.stderr
    assert "question" in result.stderr


# Spec: "Every row must contain all fields referenced by the prompt templates"
# -- including fields referenced only by the system prompt.
def test_missing_system_prompt_field_exits_1(server, run_cli):
    config = make_config(
        server.url, prompt={"system": "Style: {style}", "user": "{question}"}
    )
    result = run_cli(config, [{"question": "q", "answer": "42"}])
    assert result.exit_code == 1
    assert "style" in result.stderr


# Spec: "When the configured evaluation uses answer_field, each row must also
# contain that field." (T10: treated as an input error.)
def test_row_missing_answer_field_exits_1(server, run_cli):
    result = run_cli(make_config(server.url), [{"question": "q"}])
    assert result.exit_code == 1
    assert "answer" in result.stderr


# Spec: "1: configuration or input error" -- a line that is not valid JSON.
def test_malformed_jsonl_line_exits_1(server, run_cli):
    result = run_cli(make_config(server.url), '{"question": "q", "answer": "1"}\nnot json\n')
    assert result.exit_code == 1
    assert result.stderr.strip()


# Spec: "1: configuration or input error" -- the input file is absent.
def test_missing_input_file_exits_1(server, tmp_path):
    config_path = tmp_path / "task.yaml"
    config_path.write_text(yaml.safe_dump(make_config(server.url)))
    proc = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "rejector.py"),
            "run",
            "--config",
            str(config_path),
            "--input",
            str(tmp_path / "absent.jsonl"),
            "--output",
            str(tmp_path / "out.jsonl"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert proc.stderr.strip()


# Spec: "1: configuration or input error" -- a validation failure must not
# leave a half-written output file behind. (T14)
def test_no_output_file_written_on_input_error(server, run_cli):
    result = run_cli(make_config(server.url), [{"text": "hello"}])
    assert result.exit_code == 1
    assert not result.output_path.exists()
    assert server.call_count == 0


# Spec: "input is the original row, unchanged" -- extra fields survive.
def test_input_row_is_echoed_unchanged(server, run_cli):
    row = {"question": "q", "answer": "42", "id": 7, "tags": ["a", "b"]}
    result = run_cli(make_config(server.url), [row])
    assert result.rows[0]["input"] == row
