"""Prompt template rendering and per-row field requirements."""

from __future__ import annotations

import pytest

from conftest import base_task
from fake_api import FakeAPI, always

from taskrunner.config import build_run_config
from taskrunner.prompts import (
    MissingFieldError,
    render,
    render_messages,
    template_fields,
)


def config_for(task: dict):
    return next(iter(build_run_config({"task": task}, {}).tasks.values()))


# Spec: "prompt.system and prompt.user use {field} placeholders resolved from
# each input row."
# Context: Configuration.
def test_render_substitutes_row_fields():
    assert render("Q: {question}", {"question": "2+2?"}) == "Q: 2+2?"


def test_render_substitutes_every_occurrence_and_multiple_fields():
    rendered = render("{a} then {b} then {a}", {"a": "x", "b": "y"})
    assert rendered == "x then y then x"


def test_render_stringifies_non_string_values():
    assert render("{n} and {f}", {"n": 3, "f": 1.5}) == "3 and 1.5"


# Spec: "{field} placeholders" — only that form is documented, so unrelated
# braces stay literal (see AMBIGUITIES T11).
# Context: Configuration.
def test_unrelated_braces_are_left_alone():
    assert render('Return {"k": 1} for {q}', {"q": "now"}) == 'Return {"k": 1} for now'


def test_template_fields_lists_placeholders():
    assert template_fields("{a} {b} {a}") == ["a", "b"]


# Spec: "If a placeholder references a missing field, exit with code 1"
# Context: Configuration.
def test_render_raises_on_missing_field():
    with pytest.raises(MissingFieldError) as excinfo:
        render("{question}", {"text": "hello"})
    assert excinfo.value.field == "question"


# Spec: API contract messages: system then user.
# Context: API Contract.
def test_build_messages_orders_system_then_user():
    config = config_for(base_task("http://localhost:8000"))
    messages = render_messages(config.prompt, {"question": "2+2?"})
    assert messages == [
        {"role": "system", "content": config.prompt.system},
        {"role": "user", "content": "2+2?"},
    ]


def test_build_messages_omits_absent_system_prompt():
    task = base_task("http://localhost:8000")
    task["prompt"] = {"user": "{question}"}
    messages = render_messages(config_for(task).prompt, {"question": "2+2?"})
    assert messages == [{"role": "user", "content": "2+2?"}]


# Spec: "If a prompt template references {question} and row 0 is
# {"text": "hello"}, exit with code 1 and print an error to stderr naming row 0
# and missing field question."
# Context: Examples.
def test_missing_prompt_field_exits_one_naming_row_and_field(
    write_config, write_input, run_cli
):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"text": "hello"}])
        result = run_cli(config, data)
        assert api.call_count == 0
    assert result.returncode == 1
    assert "0" in result.stderr
    assert "question" in result.stderr


# Spec: "If a placeholder references a missing field, exit with code 1 and
# print an error to stderr naming the row index and missing field."
# Context: Configuration; the index is the offending row, not always zero.
def test_missing_field_reports_the_offending_row_index(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input(
            [
                {"question": "a", "answer": "1"},
                {"question": "b", "answer": "2"},
                {"answer": "3"},
            ]
        )
        result = run_cli(config, data)
    assert result.returncode == 1
    assert "2" in result.stderr
    assert "question" in result.stderr


# Spec: "When the configured evaluation uses answer_field, each row must also
# contain that field." (see AMBIGUITIES T9)
# Context: Input.
def test_missing_answer_field_exits_one(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q"}])
        result = run_cli(config, data)
        assert api.call_count == 0
    assert result.returncode == 1
    assert "answer" in result.stderr


# Spec: "regex requires pattern and does not require answer_field"
# Context: Input / validation rules; no per-row answer is needed either.
def test_regex_evaluation_needs_no_answer_field_in_rows(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url)
        task["evaluation"] = {"type": "regex", "pattern": r"####\s*\d+"}
        config = write_config(task)
        data = write_input([{"question": "q"}])
        result = run_cli(config, data)
    assert result.returncode == 0
    assert result.rows[0]["result"]["passed"] is True


# Spec: "prompt.system and prompt.user use {field} placeholders resolved from
# each input row."
# Context: Configuration; both templates are rendered per row.
def test_system_prompt_placeholders_are_rendered(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url)
        task["prompt"] = {"system": "You solve {topic} problems.", "user": "{question}"}
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5", "topic": "algebra"}])
        run_cli(config, data)
        assert api.requests[0]["messages"][0]["content"] == "You solve algebra problems."
