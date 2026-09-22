"""Config parsing for the `agentic` scheme and its `tools` section."""

from __future__ import annotations

from copy import deepcopy

import pytest

from rejlib.config import load_config
from rejlib.errors import ConfigError
from tests.conftest import AGENTIC_TASK, agentic_config


def load(cli, config) -> object:
    return load_config(cli.write_config(config)).only


def tools_config(*handlers: dict, **overrides) -> dict:
    """The spec's agentic task with its tool list replaced by ``handlers``."""
    tools = [
        {"name": f"tool_{index}", "description": "d",
         "parameters": {"type": "object", "properties": {}, "required": []},
         "handler": handler}
        for index, handler in enumerate(handlers)
    ]
    return agentic_config(tools=tools, **overrides)


# 'generation: scheme: "agentic"'
def test_agentic_is_an_accepted_scheme(cli):
    assert load(cli, agentic_config()).generation.scheme == "agentic"


# 'generation: max_iterations: 10'
def test_max_iterations_is_read_from_generation(cli):
    config = agentic_config(generation={"max_iterations": 4})
    assert load(cli, config).generation.max_iterations == 4


# "If max_iterations is reached first" - the limit has to exist when omitted.
def test_max_iterations_defaults_when_omitted(cli):
    config = agentic_config()
    del config["task"]["generation"]["max_iterations"]
    assert load(cli, config).generation.max_iterations == 10


# 'generation: temperature: 0.0' in the spec's own agentic example.
def test_agentic_accepts_a_zero_temperature(cli):
    assert load(cli, agentic_config()).generation.temperature == 0.0


# "max_iterations" is a count of API requests, so it must be a positive integer.
@pytest.mark.parametrize("value", [0, -1, "many", 1.5])
def test_max_iterations_must_be_a_positive_integer(cli, value):
    with pytest.raises(ConfigError, match="max_iterations"):
        load(cli, agentic_config(generation={"max_iterations": value}))


# "tools: - name: ... description: ... parameters: ... handler: ..."
def test_tool_definitions_are_read_in_order(cli):
    tools = load(cli, agentic_config()).tools
    assert [tool.name for tool in tools] == ["lookup", "calculate"]
    assert tools[0].description == "Look up a value in the database by key"
    assert tools[0].parameters == AGENTIC_TASK["tools"][0]["parameters"]


# A task may leave `tools` out; the loop then simply never calls one.
def test_tools_are_optional(cli):
    config = agentic_config()
    del config["task"]["tools"]
    assert load(cli, config).tools == ()


def test_tools_must_be_a_list(cli):
    with pytest.raises(ConfigError, match="tools"):
        load(cli, agentic_config(tools={"name": "lookup"}))


def test_a_tool_needs_a_name(cli):
    config = agentic_config()
    del config["task"]["tools"][0]["name"]
    with pytest.raises(ConfigError, match="name"):
        load(cli, config)


# 'handler: type: "echo" | "static_map" | "script"'
@pytest.mark.parametrize("handler", [
    {"type": "echo"},
    {"type": "static_map", "mapping": {"a": "b"}},
    {"type": "script", "command": "python3 -c", "arg_field": "code"},
])
def test_every_documented_handler_type_loads(cli, handler):
    assert load(cli, tools_config(handler)).tools[0].handler.type == handler["type"]


def test_unknown_handler_types_are_rejected(cli):
    with pytest.raises(ConfigError, match="handler.type"):
        load(cli, tools_config({"type": "webhook"}))


def test_a_tool_needs_a_handler(cli):
    config = agentic_config()
    del config["task"]["tools"][1]["handler"]
    with pytest.raises(ConfigError, match="handler"):
        load(cli, config)


# 'static_map: look up the first required parameter in `mapping`'
def test_static_map_mapping_is_required(cli):
    with pytest.raises(ConfigError, match="mapping"):
        load(cli, tools_config({"type": "static_map"}))


# 'if absent, return `default`, which defaults to "NOT_FOUND"'
def test_static_map_default_defaults_to_not_found(cli):
    handler = load(cli, tools_config({"type": "static_map", "mapping": {}})).tools[0].handler
    assert handler.default == "NOT_FOUND"


def test_static_map_default_is_read_from_the_config(cli):
    tools = load(cli, agentic_config()).tools
    assert tools[0].handler.default == "KEY_NOT_FOUND"
    assert tools[0].handler.mapping["revenue_q2"] == "1480000"


# 'handler: type: "script" / command: "python3 -c" / arg_field: "code"'
def test_script_handler_reads_command_and_arg_field(cli):
    handler = load(cli, tools_config(
        {"type": "script", "command": "python3 -c", "arg_field": "code"}
    )).tools[0].handler
    assert handler.command == "python3 -c"
    assert handler.arg_field == "code"


@pytest.mark.parametrize("missing", ["command", "arg_field"])
def test_script_handler_requires_both_of_its_fields(cli, missing):
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    del handler[missing]
    with pytest.raises(ConfigError, match=missing):
        load(cli, tools_config(handler))


# "defaults" / per-task merging keeps working for the new keys.
def test_tools_can_come_from_the_defaults_section(cli):
    body = deepcopy(AGENTIC_TASK)
    tools = body.pop("tools")
    config = {
        "defaults": {"api_url": "http://localhost:8000", "model": "gpt-4", "tools": tools},
        "tasks": {"data_lookup": body},
    }
    loaded = load_config(cli.write_config(config)).tasks["data_lookup"]
    assert [tool.name for tool in loaded.tools] == ["lookup", "calculate"]
