"""Configuration of the agentic scheme, the API type and the chat template."""

import pathlib

import pytest
import yaml
from test_config import NO_OVERRIDES, load

from config import DEFAULT_MAX_ITERATIONS, load_tasks
from errors import RejectorError

TOOLS = [
    {
        "name": "lookup",
        "description": "Look up a value in the database by key",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
        "handler": {"type": "static_map", "mapping": {"employees": "142"}},
    }
]

AGENTIC = {"generation": {"scheme": "agentic", "max_iterations": 4, "temperature": 0.0}, "tools": TOOLS}


def test_agentic_task_keeps_its_tools_and_iteration_limit(tmp_path):
    task = load(tmp_path, AGENTIC)
    assert task.agentic
    assert task.generation.max_iterations == 4
    assert [tool.name for tool in task.tools] == ["lookup"]


def test_max_iterations_defaults(tmp_path):
    task = load(tmp_path, {"generation": {"scheme": "agentic"}, "tools": TOOLS})
    assert task.generation.max_iterations == DEFAULT_MAX_ITERATIONS


def test_agentic_allows_a_zero_temperature(tmp_path):
    assert load(tmp_path, AGENTIC).generation.temperature == 0.0


def test_agentic_without_tools_is_rejected(tmp_path):
    with pytest.raises(RejectorError, match="tools is required for scheme 'agentic'"):
        load(tmp_path, {"generation": {"scheme": "agentic"}})


def test_agentic_may_be_selected_by_flag(tmp_path):
    task = load(tmp_path, {"tools": TOOLS}, scheme="agentic")
    assert task.agentic


def test_a_task_defaults_to_the_chat_api(tmp_path):
    task = load(tmp_path)
    assert (task.api_type, task.chat_template, task.tools) == ("chat", "chatml", ())


def test_completions_api_and_template_come_from_the_config(tmp_path):
    task = load(tmp_path, {"api_type": "completions", "chat_template": "llama3"})
    assert (task.api_type, task.chat_template) == ("completions", "llama3")


def test_flags_override_the_configured_api_type_and_template(tmp_path):
    task = load(tmp_path, {"api_type": "chat"}, api_type="completions", chat_template="mistral")
    assert (task.api_type, task.chat_template) == ("completions", "mistral")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"api_type": "grpc"}, "api_type must be one of"),
        ({"chat_template": "alpaca"}, "chat_template must be one of"),
        ({"generation": {"scheme": "agentic", "max_iterations": 0}, "tools": TOOLS}, "max_iterations must be >= 1"),
    ],
)
def test_invalid_settings_are_rejected(tmp_path, changes, message):
    with pytest.raises(RejectorError, match=message):
        load(tmp_path, changes)


def test_a_bad_tool_names_its_position(tmp_path):
    with pytest.raises(RejectorError, match=r"task.tools\[1\].name is required"):
        load(tmp_path, {"generation": {"scheme": "agentic"}, "tools": [*TOOLS, {"description": "nameless"}]})


def test_defaults_supply_the_api_type_to_every_task(tmp_path):
    document = {
        "defaults": {"api_url": "http://localhost:8000", "model": "gpt-4", "api_type": "completions",
                     "chat_template": "zephyr"},
        "tasks": {
            "gsm8k": {"prompt": {"user": "{question}"}, "output_field": "solution"},
            "mmlu": {"prompt": {"user": "{question}"}, "output_field": "choice", "chat_template": "mistral"},
        },
    }
    path = tmp_path / "multi.yaml"
    path.write_text(yaml.safe_dump(document))

    tasks = load_tasks(str(path), NO_OVERRIDES).tasks
    assert [task.api_type for task in tasks] == ["completions", "completions"]
    assert [task.chat_template for task in tasks] == ["zephyr", "mistral"]


def test_the_example_agentic_config_loads():
    path = pathlib.Path(__file__).resolve().parent.parent / "examples" / "agentic.yaml"
    task = load_tasks(str(path), NO_OVERRIDES).tasks[0]
    assert task.agentic and [tool.name for tool in task.tools] == ["lookup", "calculate"]
