"""Configuration of the `agentic` scheme: its settings and its tool blocks."""

from __future__ import annotations

from conftest import CALCULATE_TOOL, LOOKUP_TOOL, agentic_config, turn_responder
from mock_server import Reply

ROW = [{"question": "How many employees?", "answer": "142"}]
FINAL = turn_responder(Reply(content="The company has 142 employees."))


# Spec: "Extend the pipeline with an `agentic` generation mode" -- a task whose
# `generation.scheme` is "agentic" is a valid configuration.
def test_agentic_scheme_is_accepted(servers, run_cli):
    server = servers(responder=FINAL)
    result = run_cli(agentic_config(server.url), ROW)
    assert result.exit_code == 0, result.stderr
    assert result.rows[0]["output"] == {"answer": "The company has 142 employees."}


# Spec: the agentic example configures `temperature: 0.0`, which the sampling
# schemes reject.
def test_agentic_allows_zero_temperature(servers, run_cli):
    server = servers(responder=FINAL)
    result = run_cli(agentic_config(server.url, generation={"temperature": 0.0}), ROW)
    assert result.exit_code == 0, result.stderr
    assert server.payloads[0]["temperature"] == 0.0


# Spec: "generation: scheme: agentic ... temperature: 0.0" -- a temperature the
# task does give is sent as configured.
def test_agentic_sends_the_configured_temperature(servers, run_cli):
    server = servers(responder=FINAL)
    result = run_cli(agentic_config(server.url, generation={"temperature": 0.7}), ROW)
    assert result.exit_code == 0, result.stderr
    assert server.payloads[0]["temperature"] == 0.7


# Spec: "max_iterations: 10" is part of the agentic generation block.
def test_max_iterations_must_be_a_positive_integer(servers, run_cli):
    server = servers(responder=FINAL)
    config = agentic_config(server.url, generation={"max_iterations": 0})
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "max_iterations" in result.stderr


# Spec: handler types are "echo", "static_map" and "script".
def test_unknown_handler_type_exits_1(servers, run_cli):
    server = servers(responder=FINAL)
    tool = {**LOOKUP_TOOL, "handler": {"type": "oracle"}}
    result = run_cli(agentic_config(server.url, tools=[tool]), ROW)
    assert result.exit_code == 1
    assert "oracle" in result.stderr


# Spec: every tool carries a `name`, a `description`, `parameters` and a
# `handler`.
def test_tool_without_a_name_exits_1(servers, run_cli):
    server = servers(responder=FINAL)
    tool = {key: value for key, value in LOOKUP_TOOL.items() if key != "name"}
    result = run_cli(agentic_config(server.url, tools=[tool]), ROW)
    assert result.exit_code == 1
    assert "name" in result.stderr


# Spec: a task may declare several tools ("lookup" and "calculate" in the
# example).
def test_several_tools_are_all_declared(servers, run_cli):
    server = servers(responder=FINAL)
    config = agentic_config(server.url, tools=[LOOKUP_TOOL, CALCULATE_TOOL])
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    names = [tool["function"]["name"] for tool in server.payloads[0]["tools"]]
    assert names == ["lookup", "calculate"]


# Spec: "--api-type <chat|completions>" -- other values are rejected.
def test_unknown_api_type_exits_1(servers, run_cli):
    server = servers(responder=FINAL)
    result = run_cli(agentic_config(server.url, api_type="grpc"), ROW)
    assert result.exit_code == 1


# Spec: "--chat-template <chatml|llama3|mistral|zephyr>".
def test_unknown_chat_template_exits_1(servers, run_cli):
    server = servers(responder=FINAL)
    config = agentic_config(server.url, api_type="completions", chat_template="alpaca")
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "alpaca" in result.stderr
