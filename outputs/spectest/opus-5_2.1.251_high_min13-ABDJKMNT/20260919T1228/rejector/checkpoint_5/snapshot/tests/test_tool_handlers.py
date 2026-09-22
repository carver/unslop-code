"""Tool handlers, exercised directly against the tools module."""

from __future__ import annotations

import asyncio
import json

import pytest

from rejector_lib.errors import ConfigError
from rejector_lib.tools import build_tools, invoke_tool

MAPPING = {"revenue_q1": "1250000", "employees": "142"}


def tool(handler: dict, required=("key",), extra_properties=None) -> object:
    """One built tool definition with `handler`, for handler-level tests."""
    properties = {name: {"type": "string"} for name in required}
    properties.update(extra_properties or {})
    raw = {
        "name": "lookup",
        "description": "Look something up",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(required),
        },
        "handler": handler,
    }
    return build_tools([raw])[0]


def call(handler: dict, args: dict, **kwargs) -> str:
    return asyncio.run(invoke_tool(tool(handler, **kwargs), args))


# Spec: "`echo`: return the parsed tool arguments as a JSON string".
def test_echo_returns_the_arguments_as_json():
    result = call({"type": "echo"}, {"expression": "2 + 2"})
    assert json.loads(result) == {"expression": "2 + 2"}


# Spec: "`static_map`: look up the first required parameter in `mapping`".
def test_static_map_returns_the_mapped_value():
    handler = {"type": "static_map", "mapping": MAPPING, "default": "KEY_NOT_FOUND"}
    assert call(handler, {"key": "employees"}) == "142"


# Spec: "if absent, return `default`".
def test_static_map_returns_the_configured_default():
    handler = {"type": "static_map", "mapping": MAPPING, "default": "KEY_NOT_FOUND"}
    assert call(handler, {"key": "headcount"}) == "KEY_NOT_FOUND"


# Spec: "`default`, which defaults to `\"NOT_FOUND\"`".
def test_static_map_default_default_is_not_found():
    assert call({"type": "static_map", "mapping": MAPPING}, {"key": "nope"}) == "NOT_FOUND"


# Spec: "look up the *first required parameter*" -- not just any argument. (T60)
def test_static_map_uses_the_first_required_parameter():
    handler = {"type": "static_map", "mapping": MAPPING}
    args = {"scope": "all", "key": "revenue_q1"}
    result = call(handler, args, required=("key", "scope"))
    assert result == "1250000"


# Spec: "`script`: run `command` with the value of `arg_field` as a single
# command-line argument, capture stdout, and return it".
def test_script_returns_stdout():
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    result = call(handler, {"code": "print(6 * 7)"}, required=("code",))
    assert result == "42"


# Spec: "run `command` with the value of `arg_field` as a *single* command-line
# argument" -- the argument is not split on its spaces or quotes. (T62)
def test_script_passes_one_argument():
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    result = call(handler, {"code": "print('a b c')"}, required=("code",))
    assert result == "a b c"


# Spec: "on ... non-zero exit, return `\"ERROR: <stderr or timeout message>\"`".
def test_script_reports_stderr_on_failure():
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    result = call(handler, {"code": "raise SystemExit('boom')"}, required=("code",))
    assert result.startswith("ERROR:")
    assert "boom" in result


# Spec: "on timeout ... return `\"ERROR: <stderr or timeout message>\"`". (T61)
def test_script_reports_a_timeout(monkeypatch):
    monkeypatch.setattr("rejector_lib.tools.SCRIPT_TIMEOUT_SECONDS", 0.2)
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    result = call(handler, {"code": "import time; time.sleep(30)"}, required=("code",))
    assert result.startswith("ERROR:")


# Spec: the `script` handler config carries `command` and `arg_field`.
def test_script_handler_requires_a_command():
    with pytest.raises(ConfigError):
        tool({"type": "script", "arg_field": "code"})
