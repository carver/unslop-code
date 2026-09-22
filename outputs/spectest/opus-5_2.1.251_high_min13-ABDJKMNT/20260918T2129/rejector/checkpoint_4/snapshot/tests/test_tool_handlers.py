"""Tool handlers: `echo`, `static_map`, and `script`."""

from __future__ import annotations

import json

from conftest import LOOKUP_TOOL, agentic_config
from fake_server import FakeAPIServer, conversation

ROW = {"question": "How many employees?", "answer": "142"}
ANSWER = "The company has 142 employees."


def _run(write_config, write_input, run_cli, config_map, calls, rows=None):
    """Run one loop whose first response asks for `calls`, then answers."""
    with FakeAPIServer(conversation([calls, ANSWER])) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input(rows or [ROW]))
        result.payloads = api.payloads
    return result


def _tool(handler: dict, name: str = "tool", **parameters) -> dict:
    """A tool declaration with the given handler and required parameters."""
    return {
        "name": name,
        "description": "a tool",
        "parameters": {
            "type": "object",
            "properties": {key: {"type": "string"} for key in parameters},
            "required": list(parameters),
        },
        "handler": handler,
    }


def _result_of(result):
    return result.rows[0]["result"]["tool_calls"][0]["result"]


# Spec: "echo: return the parsed tool arguments as a JSON string"
def test_echo_returns_the_arguments_as_json(write_config, write_input, run_cli):
    config_map = agentic_config("", tools=(_tool({"type": "echo"}, expression=True),))
    result = _run(write_config, write_input, run_cli, config_map, [("tool", {"expression": "2+2"})])

    assert json.loads(_result_of(result)) == {"expression": "2+2"}


# Spec: "static_map: look up the first required parameter in `mapping`"
def test_static_map_looks_up_the_first_required_parameter(write_config, write_input, run_cli):
    config_map = agentic_config("", tools=(LOOKUP_TOOL,))
    result = _run(write_config, write_input, run_cli, config_map, [("lookup", {"key": "revenue_q1"})])

    assert _result_of(result) == "1250000"


# Spec: "if absent, return `default`" - the task example's KEY_NOT_FOUND
def test_static_map_returns_the_configured_default(write_config, write_input, run_cli):
    config_map = agentic_config("", tools=(LOOKUP_TOOL,))
    result = _run(write_config, write_input, run_cli, config_map, [("lookup", {"key": "profit"})])

    assert _result_of(result) == "KEY_NOT_FOUND"


# Spec: "`default`, which defaults to `"NOT_FOUND"`"
def test_static_map_default_is_not_found(write_config, write_input, run_cli):
    handler = {"type": "static_map", "mapping": {"employees": "142"}}
    config_map = agentic_config("", tools=(_tool(handler, key=True),))
    result = _run(write_config, write_input, run_cli, config_map, [("tool", {"key": "profit"})])

    assert _result_of(result) == "NOT_FOUND"


# Spec: "script: run `command` with the value of `arg_field` as a single
# command-line argument, capture stdout, and return it"
def test_script_returns_stdout(write_config, write_input, run_cli):
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    config_map = agentic_config("", tools=(_tool(handler, code=True),))
    result = _run(write_config, write_input, run_cli, config_map, [("tool", {"code": "print(6*7)"})])

    assert _result_of(result) == "42"


# Spec: "run `command` with the value of `arg_field` as a single command-line
# argument" - the value is one argv entry, not a shell fragment
def test_script_passes_the_argument_as_one_argv_entry(write_config, write_input, run_cli):
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    config_map = agentic_config("", tools=(_tool(handler, code=True),))
    result = _run(
        write_config, write_input, run_cli, config_map,
        [("tool", {"code": "print('a b' + ' | c')"})],
    )

    assert _result_of(result) == "a b | c"


# Spec: "on timeout or non-zero exit, return `"ERROR: <stderr or timeout
# message>"`"
def test_script_reports_a_non_zero_exit_as_an_error(write_config, write_input, run_cli):
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    config_map = agentic_config("", tools=(_tool(handler, code=True),))
    result = _run(
        write_config, write_input, run_cli, config_map,
        [("tool", {"code": "raise SystemExit('boom')"})],
    )

    assert _result_of(result).startswith("ERROR: ")
    assert "boom" in _result_of(result)


# Spec: "on timeout ... return `"ERROR: <stderr or timeout message>"`"
def test_script_reports_a_timeout_as_an_error(write_config, write_input, run_cli):
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code", "timeout": 1}
    config_map = agentic_config("", tools=(_tool(handler, code=True),))
    result = _run(
        write_config, write_input, run_cli, config_map,
        [("tool", {"code": "import time; time.sleep(30)"})],
    )

    assert _result_of(result).startswith("ERROR: ")


# Spec: "execute every tool call" - a result is produced even when the model
# names a tool the task does not declare
def test_unknown_tool_name_yields_an_error_result(write_config, write_input, run_cli):
    config_map = agentic_config("", tools=(LOOKUP_TOOL,))
    result = _run(write_config, write_input, run_cli, config_map, [("missing", {"key": "x"})])

    assert _result_of(result).startswith("ERROR: ")
    assert result.rows[0]["output"] == {"answer": ANSWER}
