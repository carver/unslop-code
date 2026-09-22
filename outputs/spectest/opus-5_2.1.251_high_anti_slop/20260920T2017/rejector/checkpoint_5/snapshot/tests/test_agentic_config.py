"""Validation of the agentic scheme, its tools, and the completions settings."""

import pytest
import yaml

from config import load_config
from errors import ConfigError
from tools import EchoHandler, ScriptHandler, StaticMapHandler

LOOKUP = {
    "name": "lookup",
    "description": "Look up a value in the database by key",
    "parameters": {
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    },
    "handler": {"type": "static_map", "mapping": {"employees": "142"}, "default": "KEY_NOT_FOUND"},
}

BASE = {
    "name": "t",
    "api_url": "http://localhost:8000",
    "model": "gpt-4",
    "rpm": 60,
    "prompt": {"system": "s", "user": "{question}"},
    "generation": {"scheme": "agentic", "max_iterations": 10, "temperature": 0.0},
    "evaluation": {"type": "exact_match", "answer_field": "answer"},
    "output_field": "answer",
    "tools": [LOOKUP],
}


def load_task(tmp_path, overrides=None, **changes):
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": {**BASE, **changes}}))
    return load_config(str(path), overrides).tasks[0]


def with_tool(tmp_path, **tool_changes):
    return load_task(tmp_path, tools=[{**LOOKUP, **tool_changes}]).tools[0]


def test_an_agentic_task_keeps_temperature_zero(tmp_path):
    """Unlike the sampling schemes, agentic does not need a temperature above 0."""
    assert load_task(tmp_path).generation.temperature == 0.0


def test_max_iterations_defaults_to_ten(tmp_path):
    assert load_task(tmp_path, generation={"scheme": "agentic"}).generation.max_iterations == 10


def test_max_iterations_must_be_positive(tmp_path):
    with pytest.raises(ConfigError, match="max_iterations must be >= 1"):
        load_task(tmp_path, generation={"scheme": "agentic", "max_iterations": 0})


def test_a_tool_is_read_with_its_handler(tmp_path):
    tool = load_task(tmp_path).tools[0]

    assert tool.name == "lookup"
    assert tool.parameters["required"] == ["key"]
    assert tool.handler == StaticMapHandler("key", {"employees": "142"}, "KEY_NOT_FOUND")


def test_a_static_map_defaults_to_not_found(tmp_path):
    handler = {"type": "static_map", "mapping": {"employees": "142"}}
    assert with_tool(tmp_path, handler=handler).handler.default == "NOT_FOUND"


def test_a_static_map_needs_a_required_parameter(tmp_path):
    with pytest.raises(ConfigError, match="must declare a required parameter"):
        with_tool(tmp_path, parameters={"type": "object", "properties": {}})


def test_the_other_handler_types_are_read(tmp_path):
    assert with_tool(tmp_path, handler={"type": "echo"}).handler == EchoHandler()
    script = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    assert with_tool(tmp_path, handler=script).handler == ScriptHandler("python3 -c", "code")


def test_an_unknown_handler_type_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="handler.type must be one of"):
        with_tool(tmp_path, handler={"type": "webhook"})


def test_a_script_handler_needs_its_command(tmp_path):
    with pytest.raises(ConfigError, match="handler.arg_field is required"):
        with_tool(tmp_path, handler={"type": "script", "command": "python3 -c"})


def test_a_tool_needs_a_description(tmp_path):
    with pytest.raises(ConfigError, match=r"tools\[0\].description is required"):
        load_task(tmp_path, tools=[{k: v for k, v in LOOKUP.items() if k != "description"}])


def test_a_task_declares_no_tools_by_default(tmp_path):
    assert load_task(tmp_path, tools=None).tools == ()


def test_api_type_and_chat_template_default_to_chat(tmp_path):
    task = load_task(tmp_path)
    assert (task.api_type, task.chat_template) == ("chat", "chatml")


def test_completions_settings_are_read(tmp_path):
    task = load_task(tmp_path, api_type="completions", chat_template="llama3")
    assert (task.api_type, task.chat_template) == ("completions", "llama3")


def test_cli_flags_override_the_configured_endpoint(tmp_path):
    overrides = {"api_type": "completions", "chat_template": "zephyr"}
    task = load_task(tmp_path, overrides, api_type="chat", chat_template="chatml")
    assert (task.api_type, task.chat_template) == ("completions", "zephyr")


def test_an_unknown_api_type_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="api_type must be one of"):
        load_task(tmp_path, api_type="responses")


def test_defaults_supply_the_endpoint_to_every_task(tmp_path):
    path = tmp_path / "multi.yaml"
    defaults = {"api_type": "completions", "chat_template": "mistral"}
    path.write_text(yaml.safe_dump({"defaults": defaults, "tasks": {"a": BASE, "b": BASE}}))

    tasks = load_config(str(path)).tasks
    assert all(task.api_type == "completions" for task in tasks)
    assert all(task.chat_template == "mistral" for task in tasks)
