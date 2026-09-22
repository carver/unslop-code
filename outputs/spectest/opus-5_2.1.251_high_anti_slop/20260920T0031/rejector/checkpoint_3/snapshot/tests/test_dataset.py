"""JSONL loading, prompt rendering and row validation."""

import json

import pytest

from config import GenerationConfig, PromptConfig, TaskConfig
from dataset import load_rows, prepare_messages, write_results
from errors import RejectorError
from evaluation import EvaluationConfig


def make_task(system="Solve {topic} problems.", user="{question}", evaluation=None):
    return TaskConfig(
        name="demo",
        api_url="http://localhost:8000",
        model="gpt-4",
        rpm=60,
        prompt=PromptConfig(system=system, user=user),
        generation=GenerationConfig(scheme="greedy", temperature=0.0, max_tokens=64, n=1),
        evaluation=evaluation,
        output_field="solution",
    )


def write_jsonl(tmp_path, lines):
    path = tmp_path / "input.jsonl"
    path.write_text("".join(lines))
    return str(path)


def test_load_rows_preserves_order_and_skips_blank_lines(tmp_path):
    path = write_jsonl(tmp_path, ['{"a": 1}\n', "\n", '{"a": 2}\n'])
    assert load_rows(path) == [{"a": 1}, {"a": 2}]


def test_load_rows_reports_the_offending_row(tmp_path):
    path = write_jsonl(tmp_path, ['{"a": 1}\n', "not json\n"])
    with pytest.raises(RejectorError, match="input row 1: invalid JSON"):
        load_rows(path)


def test_load_rows_rejects_non_objects(tmp_path):
    with pytest.raises(RejectorError, match="input row 0"):
        load_rows(write_jsonl(tmp_path, ["[1, 2]\n"]))


def test_prepare_messages_renders_both_roles():
    rows = [{"topic": "algebra", "question": "2 + 3?"}]
    assert prepare_messages(rows, make_task()) == [
        [
            {"role": "system", "content": "Solve algebra problems."},
            {"role": "user", "content": "2 + 3?"},
        ]
    ]


def test_prepare_messages_omits_an_empty_system_prompt():
    messages = prepare_messages([{"question": "2 + 3?"}], make_task(system=""))
    assert [message["role"] for message in messages[0]] == ["user"]


def test_prepare_messages_names_row_and_missing_field():
    with pytest.raises(RejectorError, match="input row 1: missing field 'question'"):
        prepare_messages([{"question": "ok"}, {"text": "hello"}], make_task(system=""))


def test_prepare_messages_requires_the_answer_field():
    evaluation = EvaluationConfig(type="exact_match", extract="full", answer_field="answer")
    with pytest.raises(RejectorError, match="missing field 'answer'"):
        prepare_messages([{"question": "ok"}], make_task(system="", evaluation=evaluation))


def test_malformed_template_is_reported():
    with pytest.raises(RejectorError, match="template is malformed"):
        prepare_messages([{"question": "ok"}], make_task(system="{", user="{question}"))


def test_write_results_writes_one_object_per_line(tmp_path):
    path = tmp_path / "out.jsonl"
    write_results(str(path), [{"input": {"a": 1}}, {"input": {"a": 2}}])
    assert [json.loads(line) for line in path.read_text().splitlines()] == [{"input": {"a": 1}}, {"input": {"a": 2}}]
