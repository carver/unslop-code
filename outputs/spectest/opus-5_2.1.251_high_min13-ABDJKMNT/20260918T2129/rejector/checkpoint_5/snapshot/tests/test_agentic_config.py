"""Configuring an agentic task: the scheme, `max_iterations`, and `tools`."""

from __future__ import annotations

from conftest import CALCULATE_TOOL, LOOKUP_TOOL, agentic_config
from fake_server import FakeAPIServer, always, conversation

ROW = {"question": "How many employees?", "answer": "142"}
ANSWER = "The company has 142 employees."


def _run(write_config, write_input, run_cli, config_map, *extra, responder=None, rows=None):
    with FakeAPIServer(responder or always(ANSWER)) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input(rows or [ROW]), *extra)
        result.payloads = api.payloads
    return result


# Spec: `generation: scheme: "agentic"` - the task example's generation block
def test_agentic_scheme_is_accepted(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    assert result.returncode == 0
    assert result.rows[0]["output"] == {"answer": ANSWER}


# Spec: "scheme: "agentic" ... temperature: 0.0" - unlike sample and
# rejection, an agentic task may decode greedily
def test_agentic_accepts_temperature_zero(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    assert result.returncode == 0
    assert result.payloads[0]["temperature"] == 0.0


# Spec: "temperature: 0.0 / max_tokens: 512" - decoding parameters still reach
# the request the loop sends
def test_agentic_sends_configured_decoding_parameters(write_config, write_input, run_cli):
    config_map = agentic_config("", generation={"temperature": 0.4, "max_tokens": 64})
    result = _run(write_config, write_input, run_cli, config_map)

    assert result.payloads[0]["temperature"] == 0.4
    assert result.payloads[0]["max_tokens"] == 64


# Spec: "--scheme <...>" from part 1 combined with the new scheme name
def test_scheme_flag_selects_agentic(write_config, write_input, run_cli):
    config_map = agentic_config("", generation={"scheme": "greedy"})
    result = _run(
        write_config, write_input, run_cli, config_map, "--scheme", "agentic",
        responder=conversation([[("lookup", {"key": "employees"})], ANSWER]),
    )

    assert result.returncode == 0
    assert result.rows[0]["result"]["iterations"] == 2


# Spec: "tools: - name: "lookup" / description / parameters" - the declaration
# a task carries for every tool
def test_tools_are_declared_per_task(write_config, write_input, run_cli):
    config_map = agentic_config("", tools=(LOOKUP_TOOL, CALCULATE_TOOL))
    result = _run(write_config, write_input, run_cli, config_map)

    assert result.returncode == 0
    assert len(result.payloads[0]["tools"]) == 2


# Spec: tool entries need a `name`
def test_tool_without_a_name_is_a_config_error(write_config, write_input, run_cli):
    tool = {key: value for key, value in LOOKUP_TOOL.items() if key != "name"}
    result = _run(write_config, write_input, run_cli, agentic_config("", tools=(tool,)))

    assert result.returncode == 1
    assert "name" in result.stderr


# Spec: every tool carries a `handler`
def test_tool_without_a_handler_is_a_config_error(write_config, write_input, run_cli):
    tool = {key: value for key, value in LOOKUP_TOOL.items() if key != "handler"}
    result = _run(write_config, write_input, run_cli, agentic_config("", tools=(tool,)))

    assert result.returncode == 1
    assert "handler" in result.stderr


# Spec: "Handler types: echo / static_map / script"
def test_unknown_handler_type_is_a_config_error(write_config, write_input, run_cli):
    tool = {**LOOKUP_TOOL, "handler": {"type": "sql"}}
    result = _run(write_config, write_input, run_cli, agentic_config("", tools=(tool,)))

    assert result.returncode == 1
    assert "sql" in result.stderr


# Spec: "static_map: look up the first required parameter in `mapping`"
def test_static_map_handler_requires_a_mapping(write_config, write_input, run_cli):
    tool = {**LOOKUP_TOOL, "handler": {"type": "static_map"}}
    result = _run(write_config, write_input, run_cli, agentic_config("", tools=(tool,)))

    assert result.returncode == 1
    assert "mapping" in result.stderr


# Spec: "script: run `command` with the value of `arg_field`"
def test_script_handler_requires_command_and_arg_field(write_config, write_input, run_cli):
    tool = {**LOOKUP_TOOL, "handler": {"type": "script", "command": "python3 -c"}}
    result = _run(write_config, write_input, run_cli, agentic_config("", tools=(tool,)))

    assert result.returncode == 1
    assert "arg_field" in result.stderr


# Spec: "max_iterations: 10" - the loop budget is a positive integer
def test_max_iterations_must_be_a_positive_integer(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config("", max_iterations=0))

    assert result.returncode == 1
    assert "max_iterations" in result.stderr


# Spec: the agentic task example declares `evaluation` and `output_field`
# alongside the tools, so the part 1 keys keep their meaning
def test_agentic_row_uses_the_configured_output_field(write_config, write_input, run_cli):
    config_map = agentic_config("", output_field="final")
    result = _run(write_config, write_input, run_cli, config_map)

    assert result.rows[0]["output"] == {"final": ANSWER}
