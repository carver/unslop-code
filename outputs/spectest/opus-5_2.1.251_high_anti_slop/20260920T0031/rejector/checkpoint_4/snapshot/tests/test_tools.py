"""Tool definitions, handler results and the text tool-call convention."""

import asyncio
import json

import pytest

from errors import RejectorError
from tools import Tool, Toolbox, ToolCall, describe, load_tools, parse_tool_calls

LOOKUP = {
    "name": "lookup",
    "description": "Look up a value in the database by key",
    "parameters": {
        "type": "object",
        "properties": {"key": {"type": "string", "description": "The database key to look up"}},
        "required": ["key"],
    },
    "handler": {
        "type": "static_map",
        "mapping": {"revenue_q1": "1250000", "employees": "142"},
        "default": "KEY_NOT_FOUND",
    },
}

CALCULATE = {
    "name": "calculate",
    "description": "Evaluate a mathematical expression",
    "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
    "handler": {"type": "echo"},
}

RUN_CODE = {
    "name": "run_code",
    "description": "Run python code",
    "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
    "handler": {"type": "script", "command": "python3 -c", "arg_field": "code"},
}


def invoke(definitions, name, args):
    toolbox = Toolbox(load_tools(definitions, "task.tools"))
    return asyncio.run(toolbox.invoke(ToolCall(id="call_1", name=name, args=args)))


def test_static_map_returns_the_mapped_value():
    assert invoke([LOOKUP], "lookup", {"key": "employees"}) == "142"


def test_static_map_falls_back_to_the_configured_default():
    assert invoke([LOOKUP], "lookup", {"key": "profit"}) == "KEY_NOT_FOUND"


def test_static_map_default_defaults_to_not_found():
    definition = {**LOOKUP, "handler": {"type": "static_map", "mapping": {"a": "1"}}}
    assert invoke([definition], "lookup", {"key": "b"}) == "NOT_FOUND"


def test_echo_returns_the_arguments_as_json():
    assert json.loads(invoke([CALCULATE], "calculate", {"expression": "1 + 1"})) == {"expression": "1 + 1"}


def test_script_returns_the_command_output():
    assert invoke([RUN_CODE], "run_code", {"code": "print(6 * 7)"}) == "42"


def test_script_reports_a_failing_command():
    result = invoke([RUN_CODE], "run_code", {"code": "raise ValueError('nope')"})
    assert result.startswith("ERROR: ") and "nope" in result


def test_script_reports_a_timeout(monkeypatch):
    monkeypatch.setattr("tools.SCRIPT_TIMEOUT_SECONDS", 0.2)
    assert invoke([RUN_CODE], "run_code", {"code": "import time; time.sleep(5)"}) == "ERROR: timed out after 0.2s"


def test_unknown_tool_is_reported_to_the_model():
    assert invoke([CALCULATE], "lookup", {"key": "x"}) == "ERROR: unknown tool 'lookup'"


def test_definition_is_an_openai_function():
    tool = load_tools([CALCULATE], "task.tools")[0]
    assert tool.definition == {
        "name": "calculate",
        "description": "Evaluate a mathematical expression",
        "parameters": CALCULATE["parameters"],
    }


@pytest.mark.parametrize(
    ("definition", "message"),
    [
        ({"description": "no name"}, "name is required"),
        ({**CALCULATE, "handler": {"type": "magic"}}, "type must be one of"),
        ({**CALCULATE, "handler": {"type": "script", "command": "python3 -c"}}, "arg_field is required"),
        ({**CALCULATE, "handler": {"type": "script", "arg_field": "code"}}, "command is required"),
        ({**CALCULATE, "handler": {"type": "static_map"}}, "mapping must be a non-empty mapping"),
        (
            {"name": "t", "parameters": {"type": "object"}, "handler": {"type": "static_map", "mapping": {"a": "1"}}},
            "required parameter",
        ),
    ],
)
def test_invalid_tool_is_rejected(definition, message):
    with pytest.raises(RejectorError, match=message):
        load_tools([definition], "task.tools")


def test_tools_section_must_be_a_non_empty_list():
    with pytest.raises(RejectorError, match="non-empty list"):
        load_tools([], "task.tools")


def test_text_tool_calls_are_parsed_in_order():
    text = (
        "Let me look these up.\n"
        '<tool_call>\n{"name": "lookup", "arguments": {"key": "revenue_q1"}}\n</tool_call>\n'
        '<tool_call>\n{"name": "lookup", "arguments": {"key": "revenue_q2"}}\n</tool_call>'
    )
    assert [(call.name, call.args) for call in parse_tool_calls(text)] == [
        ("lookup", {"key": "revenue_q1"}),
        ("lookup", {"key": "revenue_q2"}),
    ]


def test_text_without_a_tool_call_parses_to_nothing():
    assert parse_tool_calls("The company has 142 employees.") == ()


def test_unusable_tool_call_blocks_are_skipped():
    assert parse_tool_calls("<tool_call>\nnot json\n</tool_call>") == ()


def test_instructions_describe_every_tool():
    instructions = describe(load_tools([LOOKUP, CALCULATE], "task.tools"))
    assert "<tool_call>" in instructions
    assert '"name": "lookup"' in instructions and '"name": "calculate"' in instructions


def test_toolbox_keeps_its_tools_in_order():
    tools = load_tools([LOOKUP, CALCULATE], "task.tools")
    assert [tool.name for tool in Toolbox(tools).tools] == ["lookup", "calculate"]
    assert all(isinstance(tool, Tool) for tool in tools)
