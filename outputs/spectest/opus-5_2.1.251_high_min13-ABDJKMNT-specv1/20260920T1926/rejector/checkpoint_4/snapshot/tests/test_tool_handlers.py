"""Tool handler types: `echo`, `static_map` and `script`."""

from __future__ import annotations

import asyncio
import json

from conftest import CALCULATE_TOOL, LOOKUP_TOOL
from taskrunner.tools import ToolCall, build_tools, execute_calls


def run(tools: list[dict], name: str, **arguments) -> str:
    """Build the tools, invoke one of them, and return the handler's result."""
    built = build_tools(tools, "task")
    calls = [ToolCall(id="call_0", name=name, arguments=arguments)]
    return asyncio.run(execute_calls(built, calls, iteration=1))[0].result


def script_tool(**handler) -> list[dict]:
    """A tool whose `code` argument is handed to a script handler."""
    return [
        {
            "name": "run_code",
            "description": "Run Python",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
            "handler": {"type": "script", "arg_field": "code", **handler},
        }
    ]


# Spec: "`echo`: return the parsed tool arguments as a JSON string"
# Context: Handler types.
def test_echo_returns_the_arguments_as_json():
    result = run([CALCULATE_TOOL], "calculate", expression="1250000 + 1480000")
    assert json.loads(result) == {"expression": "1250000 + 1480000"}
    assert isinstance(result, str)


# Spec: "`static_map`: look up the first required parameter in `mapping`"
# Context: Handler types.
def test_static_map_looks_up_the_first_required_parameter():
    assert run([LOOKUP_TOOL], "lookup", key="employees") == "142"
    assert run([LOOKUP_TOOL], "lookup", key="revenue_q1") == "1250000"


# Spec: "if absent, return `default`"
# Context: Handler types.
def test_static_map_returns_the_configured_default():
    assert run([LOOKUP_TOOL], "lookup", key="headcount") == "KEY_NOT_FOUND"


# Spec: "`default`, which defaults to `\"NOT_FOUND\"`"
# Context: Handler types.
def test_static_map_default_default_is_not_found():
    tool = {**LOOKUP_TOOL, "handler": {"type": "static_map", "mapping": {"a": "1"}}}
    assert run([tool], "lookup", key="zzz") == "NOT_FOUND"


# Spec: "run `command` with the value of `arg_field` as a single command-line
# argument, capture stdout, and return it"
# Context: Handler types / Script handler config.
def test_script_passes_the_arg_field_as_one_argument():
    tools = script_tool(command="python3 -c")
    assert run(tools, "run_code", code="print(2 + 2)") == "4"


# Spec: "run `command` with the value of `arg_field` as a single command-line
# argument"
# Context: Handler types; spaces must not split the argument into several.
def test_script_argument_is_not_word_split():
    tools = script_tool(command="python3 -c")
    assert run(tools, "run_code", code="print('a b c')") == "a b c"


# Spec: "on timeout or non-zero exit, return `\"ERROR: <stderr or timeout
# message>\"`"
# Context: Handler types; non-zero exit.
def test_script_non_zero_exit_reports_stderr():
    tools = script_tool(command="python3 -c")
    result = run(tools, "run_code", code="raise SystemExit('nope')")
    assert result.startswith("ERROR: ")
    assert "nope" in result


# Spec: "on timeout ... return `\"ERROR: <stderr or timeout message>\"`"
# Context: Handler types; timeout.
def test_script_timeout_reports_an_error():
    tools = script_tool(command="python3 -c", timeout=0.2)
    result = run(tools, "run_code", code="import time; time.sleep(5)")
    assert result.startswith("ERROR: ")


# Spec: "execute every tool call, append the assistant tool-call message and
# the tool result messages"
# Context: Agentic loop; a name with no matching tool still has to answer.
def test_an_unknown_tool_name_yields_an_error_result():
    assert run([LOOKUP_TOOL], "nosuchtool", key="a").startswith("ERROR: ")


# Spec: "if one model response contains multiple tool calls, execute and
# record all of them for that iteration"
# Context: Agentic loop / Rules.
def test_every_call_is_executed_in_order():
    built = build_tools([LOOKUP_TOOL, CALCULATE_TOOL], "task")
    calls = [
        ToolCall(id="call_0", name="lookup", arguments={"key": "revenue_q1"}),
        ToolCall(id="call_1", name="lookup", arguments={"key": "revenue_q2"}),
    ]
    executed = asyncio.run(execute_calls(built, calls, iteration=1))
    assert [item.result for item in executed] == ["1250000", "1480000"]
    assert [item.iteration for item in executed] == [1, 1]
    assert [item.tool for item in executed] == ["lookup", "lookup"]
    assert [item.args for item in executed] == [{"key": "revenue_q1"}, {"key": "revenue_q2"}]
