"""Agentic loops in completions mode: tools in the prompt, calls in the text."""

from __future__ import annotations

from conftest import CALCULATE_TOOL, agentic_config, turn_responder
from mock_server import Reply

ROW = [{"question": "How many employees?", "answer": "142"}]
LOOKUP = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "employees"}}])
ANSWER = Reply(content="The company has 142 employees.")


def run(servers, run_cli, *replies, **overrides):
    server = servers(responder=turn_responder(*replies))
    config = agentic_config(
        server.url, api_type="completions", chat_template="chatml", **overrides
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    return server, result.rows[0]


# Spec: "tool definitions are rendered into the prompt instead of being sent as
# a native `tools` field".
def test_tools_are_rendered_into_the_prompt(servers, run_cli):
    server, _ = run(servers, run_cli, LOOKUP, ANSWER, tools=[CALCULATE_TOOL])
    payload = server.payloads[0]
    assert "tools" not in payload
    assert "calculate" in payload["prompt"]
    assert "Evaluate a mathematical expression" in payload["prompt"]


# Spec: "parse tool calls from response text blocks of the form
# `<tool_call>{\"name\": ..., \"arguments\": {...}}</tool_call>`".
def test_tool_call_blocks_are_parsed_from_the_text(servers, run_cli):
    _, row = run(servers, run_cli, LOOKUP, ANSWER)
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]
    assert row["result"]["iterations"] == 2


# Spec: "execute those calls and feed the results back into the next prompt
# iteration using the template's tool-role formatting".
def test_results_are_fed_back_into_the_next_prompt(servers, run_cli):
    server, _ = run(servers, run_cli, LOOKUP, ANSWER)
    prompt = server.payloads[1]["prompt"]
    assert "<tool_call>" in prompt
    assert "<|im_start|>tool\n142<|im_end|>" in prompt
    assert prompt.endswith("<|im_start|>assistant\n")


# Spec: "If the response contains final text and no tool calls, stop and use
# that text as the output" -- read from `choices[0].text`.
def test_final_text_becomes_the_output(servers, run_cli):
    _, row = run(servers, run_cli, LOOKUP, ANSWER)
    assert row["output"] == {"answer": "The company has 142 employees."}
    assert row["result"]["passed"] is True
    assert row["meta"]["finish_reason"] == "stop"


# Spec: "If `max_iterations` is reached first, output `null`" -- in completions
# mode too.
def test_max_iterations_in_completions_mode(servers, run_cli):
    _, row = run(servers, run_cli, LOOKUP, generation={"max_iterations": 2})
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 2
