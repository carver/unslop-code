"""Input loading, prompt rendering, and the errors they raise."""

import json

import pytest

from config import EvaluationConfig, GenerationConfig, PromptConfig, TaskConfig
from dataset import load_rows, prepare_prompts
from errors import InputError


def make_config(evaluation=None):
    return TaskConfig(
        name="t",
        api_url="http://localhost:8000",
        model="gpt-4",
        rpm=60,
        prompt=PromptConfig(system="Solve it.", user="{question}"),
        generation=GenerationConfig("greedy", 0.0, 256, n=1, max_attempts=3),
        evaluation=evaluation,
        output_field="solution",
    )


def write_rows(tmp_path, rows):
    path = tmp_path / "data.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return str(path)


def test_load_rows_keeps_order_and_skips_blank_lines(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text('{"a": 1}\n\n{"a": 2}\n')
    assert load_rows(str(path)) == [{"a": 1}, {"a": 2}]


def test_load_rows_reports_the_offending_row(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text('{"a": 1}\nnot json\n')
    with pytest.raises(InputError, match="row 1: invalid JSON"):
        load_rows(str(path))


def test_prepare_prompts_renders_placeholders(tmp_path):
    rows = load_rows(write_rows(tmp_path, [{"question": "What is 2 + 3?"}]))
    assert prepare_prompts(rows, make_config())[0].user == "What is 2 + 3?"


def test_missing_template_field_names_row_and_field(tmp_path):
    rows = load_rows(write_rows(tmp_path, [{"text": "hello"}]))
    with pytest.raises(InputError, match="row 0: missing field 'question'"):
        prepare_prompts(rows, make_config())


def test_missing_answer_field_is_reported(tmp_path):
    rows = load_rows(write_rows(tmp_path, [{"question": "q"}]))
    evaluation = EvaluationConfig("exact_match", "last_number", "answer", None)
    with pytest.raises(InputError, match="row 0: missing field 'answer'"):
        prepare_prompts(rows, make_config(evaluation))
