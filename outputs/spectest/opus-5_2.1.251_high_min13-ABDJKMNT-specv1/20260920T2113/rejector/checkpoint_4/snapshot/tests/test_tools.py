"""The three tool handler types."""

from __future__ import annotations

import asyncio
import json

import pytest

from rejlib.errors import ConfigError
from rejlib.tools import load_tools, run_tool

LOOKUP_PARAMS = {
    "type": "object",
    "properties": {"key": {"type": "string"}},
    "required": ["key"],
}


def build(handler: dict, parameters: dict | None = None, name: str = "t") -> tuple:
    return load_tools(
        [{"name": name, "description": "d",
          "parameters": parameters if parameters is not None else LOOKUP_PARAMS,
          "handler": handler}],
        "task.tools",
    )


def call(tools, name: str, args: dict) -> str:
    return asyncio.run(run_tool(tools, name, args))


# "echo: return the parsed tool arguments as a JSON string"
def test_echo_returns_the_arguments_as_json():
    tools = build({"type": "echo"})
    assert json.loads(call(tools, "t", {"expression": "1 + 1"})) == {"expression": "1 + 1"}


def test_echo_of_no_arguments_is_an_empty_object():
    assert call(build({"type": "echo"}), "t", {}) == "{}"


# "static_map: look up the first required parameter in `mapping`"
def test_static_map_looks_up_the_first_required_parameter():
    tools = build({"type": "static_map", "mapping": {"employees": "142"}})
    assert call(tools, "t", {"key": "employees"}) == "142"


def test_static_map_uses_the_first_entry_of_required_not_of_properties():
    parameters = {
        "type": "object",
        "properties": {"unused": {"type": "string"}, "key": {"type": "string"}},
        "required": ["key"],
    }
    tools = build({"type": "static_map", "mapping": {"employees": "142"}}, parameters)
    assert call(tools, "t", {"unused": "employees", "key": "employees"}) == "142"


# "if absent, return `default`"
def test_static_map_returns_the_configured_default_for_an_unknown_key():
    tools = build({"type": "static_map", "mapping": {"employees": "142"},
                   "default": "KEY_NOT_FOUND"})
    assert call(tools, "t", {"key": "headcount"}) == "KEY_NOT_FOUND"


# '`default`, which defaults to "NOT_FOUND"'
def test_static_map_default_default_is_not_found():
    tools = build({"type": "static_map", "mapping": {"employees": "142"}})
    assert call(tools, "t", {"key": "headcount"}) == "NOT_FOUND"


def test_static_map_without_the_required_argument_returns_the_default():
    tools = build({"type": "static_map", "mapping": {"employees": "142"}})
    assert call(tools, "t", {}) == "NOT_FOUND"


# "script: run `command` with the value of `arg_field` as a single command-line
#  argument, capture stdout, and return it"
def test_script_runs_the_command_with_the_argument_and_returns_stdout():
    tools = build({"type": "script", "command": "python3 -c", "arg_field": "code"})
    assert call(tools, "t", {"code": "print(6 * 7)"}) == "42"


def test_script_passes_the_argument_as_one_word_not_a_shell_string():
    tools = build({"type": "script", "command": "python3 -c", "arg_field": "code"})
    assert call(tools, "t", {"code": "print('a b'); print('c')"}) == "a b\nc"


# "on timeout or non-zero exit, return "ERROR: <stderr or timeout message>""
def test_script_reports_stderr_of_a_failing_command():
    tools = build({"type": "script", "command": "python3 -c", "arg_field": "code"})
    result = call(tools, "t", {"code": "raise SystemExit('nope')"})
    assert result.startswith("ERROR: ")
    assert "nope" in result


def test_script_reports_a_timeout(monkeypatch):
    import rejlib.tools as tools_module

    monkeypatch.setattr(tools_module, "SCRIPT_TIMEOUT_SECONDS", 0.2)
    tools = build({"type": "script", "command": "python3 -c", "arg_field": "code"})
    result = call(tools, "t", {"code": "import time; time.sleep(30)"})
    assert result.startswith("ERROR: ")
    assert "timeout" in result.lower()


def test_script_without_its_argument_field_reports_an_error():
    tools = build({"type": "script", "command": "python3 -c", "arg_field": "code"})
    assert call(tools, "t", {"other": "print(1)"}).startswith("ERROR: ")


# The model may name a tool the task does not define.
def test_calling_an_undefined_tool_returns_an_error_result():
    tools = build({"type": "echo"})
    assert call(tools, "missing", {}).startswith("ERROR: ")


def test_loading_rejects_a_tool_entry_that_is_not_a_mapping():
    with pytest.raises(ConfigError):
        load_tools(["lookup"], "task.tools")
