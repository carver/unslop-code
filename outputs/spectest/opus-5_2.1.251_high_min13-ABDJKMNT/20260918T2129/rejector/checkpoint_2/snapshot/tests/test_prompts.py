"""Prompt templating and the missing-placeholder input error."""

from __future__ import annotations

from fake_server import FakeAPIServer, always, echo_user
from conftest import base_config


# Spec: "prompt.system and prompt.user use {field} placeholders resolved from
# each input row"
def test_placeholders_are_resolved_from_the_row(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["prompt"] = {"system": "You are a {role}.", "user": "{question} ({hint})"}
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        rows = write_input([{"question": "What is 2 + 3?", "hint": "add", "role": "tutor", "answer": "5"}])
        run_cli(config, rows)
        messages = api.payloads[0]["messages"]
    assert messages[0]["content"] == "You are a tutor."
    assert messages[1]["content"] == "What is 2 + 3? (add)"


# Spec: "{field} placeholders resolved from each input row" - each row renders
# with its own values
def test_each_row_renders_its_own_prompt(write_config, write_input, run_cli):
    with FakeAPIServer(echo_user()) as api:
        config_map = base_config(api.url)
        config = write_config(config_map)
        rows = write_input([{"question": "alpha", "answer": "1"}, {"question": "beta", "answer": "2"}])
        result = run_cli(config, rows)
        rendered = sorted(p["messages"][1]["content"] for p in api.payloads)
    assert rendered == ["alpha", "beta"]
    assert [row["output"]["solution"] for row in result.rows] == ["alpha", "beta"]


# Spec: "If a placeholder references a missing field, exit with code 1 and
# print an error to stderr naming the row index and missing field."
def test_missing_placeholder_field_exits_1_naming_row_and_field(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"text": "hello"}])
        result = run_cli(config, rows)
    assert result.returncode == 1
    assert "0" in result.stderr
    assert "question" in result.stderr


# Spec: "naming the row index" - the index is the offending row, not always 0
def test_missing_field_error_names_the_offending_row_index(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([
            {"question": "q0", "answer": "1"},
            {"question": "q1", "answer": "2"},
            {"text": "oops"},
        ])
        result = run_cli(config, rows)
    assert result.returncode == 1
    assert "2" in result.stderr
    assert "question" in result.stderr


# Spec: "Every row must contain all fields referenced by the prompt templates"
# - a system-prompt placeholder counts too
def test_missing_system_placeholder_field_exits_1(write_config, write_input, run_cli):
    config_map = base_config("http://127.0.0.1:1")
    config_map["task"]["prompt"] = {"system": "Persona: {persona}", "user": "{question}"}
    config = write_config(config_map)
    rows = write_input([{"question": "q", "answer": "1"}])
    result = run_cli(config, rows)
    assert result.returncode == 1
    assert "persona" in result.stderr


# Spec: "When the configured evaluation uses answer_field, each row must also
# contain that field."
def test_row_missing_answer_field_exits_1(write_config, write_input, run_cli):
    config = write_config(base_config("http://127.0.0.1:1"))
    rows = write_input([{"question": "q"}])
    result = run_cli(config, rows)
    assert result.returncode == 1
    assert "answer" in result.stderr
    assert "0" in result.stderr


# Spec: prompt values without placeholders are sent verbatim
def test_static_prompts_are_sent_verbatim(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["prompt"] = {"system": "be terse", "user": "say hi"}
    with FakeAPIServer(always("hi")) as api:
        config_map["task"]["api_url"] = api.url
        config_map["task"]["evaluation"] = {"type": "contains", "answer_field": "answer"}
        config = write_config(config_map)
        result = run_cli(config, write_input([{"answer": "hi"}]))
        messages = api.payloads[0]["messages"]
    assert result.returncode == 0
    assert [m["content"] for m in messages] == ["be terse", "say hi"]
