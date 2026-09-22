"""The tool handlers, and how a call is dispatched to one."""

import asyncio

from tools import EchoHandler, ScriptHandler, StaticMapHandler, ToolCall, ToolConfig, invoke


def run(coroutine):
    return asyncio.run(coroutine)


def tool(name, handler):
    return ToolConfig(name, "does a thing", {"type": "object"}, handler)


def test_echo_returns_the_arguments_as_json():
    assert run(EchoHandler().run({"expression": "2 + 2"})) == '{"expression": "2 + 2"}'


def test_static_map_looks_up_its_key_field():
    handler = StaticMapHandler("key", {"employees": "142"}, "KEY_NOT_FOUND")
    assert run(handler.run({"key": "employees"})) == "142"


def test_static_map_falls_back_to_its_default():
    handler = StaticMapHandler("key", {"employees": "142"}, "KEY_NOT_FOUND")
    assert run(handler.run({"key": "revenue"})) == "KEY_NOT_FOUND"
    assert run(handler.run({})) == "KEY_NOT_FOUND"


def test_script_passes_its_arg_field_as_one_argument():
    handler = ScriptHandler("python3 -c", "code")
    assert run(handler.run({"code": "print(6 * 7)"})) == "42\n"


def test_script_reports_a_failure_as_an_error_result():
    handler = ScriptHandler("python3 -c", "code")
    result = run(handler.run({"code": "raise SystemExit('boom')"}))

    assert result.startswith("ERROR: ")
    assert "boom" in result


def test_script_reports_a_hang_as_an_error_result(monkeypatch):
    monkeypatch.setattr("tools.SCRIPT_TIMEOUT_SECONDS", 0.2)
    handler = ScriptHandler("python3 -c", "code")

    assert run(handler.run({"code": "import time; time.sleep(5)"})).startswith("ERROR: timed out")


def test_a_call_reaches_the_tool_that_shares_its_name():
    tools = (tool("echo_it", EchoHandler()), tool("lookup", StaticMapHandler("key", {"a": "1"}, "?")))
    assert run(invoke(tools, ToolCall("call_1", "lookup", {"key": "a"}))) == "1"


def test_an_unknown_tool_is_reported_back_to_the_model():
    result = run(invoke((tool("lookup", EchoHandler()),), ToolCall("call_1", "nope", {})))
    assert result == "ERROR: unknown tool 'nope'"


def test_a_call_is_replayed_in_the_openai_shape():
    message = ToolCall("call_1", "lookup", {"key": "a"}).as_message()

    assert message["type"] == "function"
    assert message["function"] == {"name": "lookup", "arguments": '{"key": "a"}'}


def test_the_definition_describes_the_tool_to_the_model():
    parameters = {"type": "object", "properties": {"key": {"type": "string"}}}
    definition = ToolConfig("lookup", "Look up a value", parameters, EchoHandler()).definition

    assert definition == {
        "type": "function",
        "function": {"name": "lookup", "description": "Look up a value", "parameters": parameters},
    }
