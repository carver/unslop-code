"""Part 4: the `echo`, `static_map`, and `script` tool handler types."""
import pytest

from conftest import agentic_config, echo_tool, script_tool, static_map_tool
from mock_api import MockAPI, agentic_turns

ROWS = [{"question": "How many employees are there?", "answer": "142"}]


def tool_result(run, index=0):
    return run.rows[0]["result"]["tool_calls"][index]["result"]


def run_with(run_tool, tools, calls, final="done", **kw):
    steps = [list(calls), final]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url, tools=tools, **kw), ROWS)
    assert run.returncode == 0, run.stderr
    return run


# Spec: "`echo`: return the parsed tool arguments as a JSON string"
# Context: Handler types.
def test_echo_returns_the_arguments_as_a_json_string(run_tool):
    run = run_with(run_tool, [echo_tool()],
                   [("calculate", {"expression": "1250000 + 1480000"})])
    assert tool_result(run) == '{"expression": "1250000 + 1480000"}'


def test_echo_returns_every_argument_it_was_given(run_tool):
    import json
    run = run_with(run_tool, [echo_tool()],
                   [("calculate", {"expression": "1+1", "precision": 2})])
    assert json.loads(tool_result(run)) == {"expression": "1+1",
                                            "precision": 2}


# Spec: "`static_map`: look up the first required parameter in `mapping`"
# Context: Handler types.
def test_static_map_looks_up_the_first_required_parameter(run_tool):
    run = run_with(run_tool, [static_map_tool()],
                   [("lookup", {"key": "revenue_q2"})])
    assert tool_result(run) == "1480000"


# Spec: "if absent, return `default`"
# Context: Handler types.
def test_static_map_returns_the_configured_default_when_absent(run_tool):
    tool = static_map_tool(default="KEY_NOT_FOUND")
    run = run_with(run_tool, [tool], [("lookup", {"key": "profit"})])
    assert tool_result(run) == "KEY_NOT_FOUND"


# Spec: "`default`, which defaults to `"NOT_FOUND"`"
# Context: Handler types.
def test_static_map_default_default_is_not_found(run_tool):
    tool = static_map_tool(default=None)
    run = run_with(run_tool, [tool], [("lookup", {"key": "profit"})])
    assert tool_result(run) == "NOT_FOUND"


def test_static_map_ignores_parameters_that_are_not_the_first_required(run_tool):
    tool = static_map_tool()
    tool["parameters"]["properties"]["scale"] = {"type": "string"}
    run = run_with(run_tool, [tool],
                   [("lookup", {"scale": "employees", "key": "revenue_q1"})])
    assert tool_result(run) == "1250000"


# Spec: "`script`: run `command` with the value of `arg_field` as a single
#        command-line argument, capture stdout, and return it"
# Context: Handler types / script handler config.
def test_script_runs_the_command_with_the_arg_field_value(run_tool):
    run = run_with(run_tool, [script_tool()],
                   [("run_code", {"code": "print(2 + 40)"})])
    assert tool_result(run) == "42"


def test_script_passes_the_argument_as_a_single_argv_entry(run_tool):
    # Spaces and shell metacharacters must survive as one argument.
    run = run_with(run_tool, [script_tool()],
                   [("run_code", {"code": "print('a b'); print('| c')"})])
    assert tool_result(run) == "a b\n| c"


def test_script_uses_the_configured_arg_field(run_tool):
    tool = script_tool(param="snippet", arg_field="snippet")
    run = run_with(run_tool, [tool], [("run_code", {"snippet": "print(7)"})])
    assert tool_result(run) == "7"


# Spec: "on timeout or non-zero exit, return `"ERROR: <stderr or timeout
#        message>"`"
# Context: Handler types.
def test_script_non_zero_exit_returns_error_with_stderr(run_tool):
    run = run_with(run_tool, [script_tool()],
                   [("run_code", {"code": "raise SystemExit('boom')"})])
    result = tool_result(run)
    assert result.startswith("ERROR: ")
    assert "boom" in result


def test_script_missing_command_returns_an_error(run_tool):
    tool = script_tool(command="definitely_not_a_real_command_xyz")
    run = run_with(run_tool, [tool], [("run_code", {"code": "print(1)"})])
    assert tool_result(run).startswith("ERROR: ")


@pytest.mark.slow
def test_script_timeout_returns_an_error(run_tool):
    tool = script_tool(timeout=1)
    run = run_with(run_tool, [tool],
                   [("run_code", {"code": "import time; time.sleep(30)"})])
    result = tool_result(run)
    assert result.startswith("ERROR: ")
    assert "timed out" in result.lower()


# Spec: the loop keeps going after a handler error; the result is fed back.
def test_error_results_are_fed_back_into_the_conversation(run_tool):
    from conftest import tool_messages
    steps = [[("run_code", {"code": "raise SystemExit('boom')"})], "sorry"]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url, tools=[script_tool()]), ROWS)
    assert run.returncode == 0, run.stderr
    assert tool_messages(api.calls[1])[0]["content"].startswith("ERROR: ")


# Spec: handlers of different types coexist on one task.
def test_a_task_may_mix_handler_types(run_tool):
    tools = [static_map_tool(), echo_tool()]
    run = run_with(run_tool, tools,
                   [("lookup", {"key": "employees"}),
                    ("calculate", {"expression": "142 * 2"})])
    calls = run.rows[0]["result"]["tool_calls"]
    assert [c["result"] for c in calls] == ["142",
                                            '{"expression": "142 * 2"}']
