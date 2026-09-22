"""Prompt template rendering and per-row field requirements."""

from __future__ import annotations

import pytest

from rejlib.config import Evaluation, load_config
from rejlib.errors import ConfigError
from rejlib.prompts import build_messages, render, validate_rows
from tests.conftest import task_config


def config_for(cli, **overrides):
    return load_config(cli.write_config(task_config(**overrides)), {})


# "prompt.system and prompt.user use {field} placeholders resolved from each
#  input row"
def test_render_substitutes_row_fields():
    row = {"question": "What is 2 + 3?", "answer": "5"}
    assert render("{question}", row) == "What is 2 + 3?"
    assert render("Q: {question} (A: {answer})", row) == "Q: What is 2 + 3? (A: 5)"


# "{field} placeholders resolved from each input row" (T17: non-string values,
# literal braces that are not placeholders are left alone)
def test_render_handles_non_strings_and_literal_braces():
    assert render("{count} items", {"count": 3}) == "3 items"
    assert render("respond as {\"k\": v} for {question}", {"question": "x"}) == (
        "respond as {\"k\": v} for x"
    )


# "messages: [{role: system, content: <rendered system prompt>},
#            {role: user, content: <rendered user prompt>}]"
def test_build_messages_renders_both_prompts(cli):
    config = config_for(cli)
    messages = build_messages(config, {"question": "What is 2 + 3?", "answer": "5"})
    assert messages == [
        {"role": "system", "content": "Solve the math problem. Final answer after ####."},
        {"role": "user", "content": "What is 2 + 3?"},
    ]


# T16: a config without prompt.system sends only the user message
def test_build_messages_omits_absent_system_prompt(cli):
    config = task_config()
    del config["task"]["prompt"]["system"]
    loaded = load_config(cli.write_config(config), {})
    assert build_messages(loaded, {"question": "hi"}) == [{"role": "user", "content": "hi"}]


# "If a placeholder references a missing field, exit with code 1 and print an
#  error to stderr naming the row index and missing field"
def test_validate_rows_names_row_index_and_field(cli):
    config = config_for(cli)
    with pytest.raises(ConfigError) as excinfo:
        validate_rows([{"question": "ok", "answer": "1"}, {"text": "hello", "answer": "1"}], config)
    message = str(excinfo.value)
    assert "1" in message and "question" in message


# "If a prompt template references {question} and row 0 is {"text": "hello"},
#  exit with code 1 and print an error to stderr naming row 0 and missing field
#  question"
def test_validate_rows_reports_row_zero(cli):
    config = config_for(cli)
    with pytest.raises(ConfigError) as excinfo:
        validate_rows([{"text": "hello"}], config)
    assert "0" in str(excinfo.value) and "question" in str(excinfo.value)


# "When the configured evaluation uses answer_field, each row must also contain
#  that field"
def test_validate_rows_requires_answer_field(cli):
    config = config_for(cli)
    with pytest.raises(ConfigError) as excinfo:
        validate_rows([{"question": "2+3"}], config)
    assert "answer" in str(excinfo.value)


# "regex requires pattern and does not require answer_field"
def test_validate_rows_skips_answer_field_for_regex(cli):
    config = config_for(cli, evaluation={"type": "regex", "pattern": r"\d+", "answer_field": None})
    validate_rows([{"question": "2+3"}], config)


# "evaluation is ... optional otherwise" - no evaluation means no answer_field need
def test_validate_rows_without_evaluation(cli):
    config = task_config()
    config["task"].pop("evaluation")
    loaded = load_config(cli.write_config(config), {})
    validate_rows([{"question": "2+3"}], loaded)
    assert loaded.evaluation is None
    assert isinstance(Evaluation(type="contains", answer_field="a"), Evaluation)
