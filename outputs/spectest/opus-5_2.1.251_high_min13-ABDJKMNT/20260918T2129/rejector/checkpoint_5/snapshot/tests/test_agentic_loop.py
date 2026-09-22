"""The agentic loop: conversation building, tool rounds, and the iteration cap."""

from __future__ import annotations

import json

import pytest
from conftest import CALCULATE_TOOL, LOOKUP_TOOL, agentic_config, icl_setup
from fake_server import (
    FakeAPIServer,
    Reply,
    conversation,
    system_of,
    tool_results_of,
    tools_of,
    turns_of,
    user_of,
)

ROW = {"question": "How many employees?", "answer": "142"}
ANSWER = "The company has 142 employees."
LOOKUP = [("lookup", {"key": "employees"})]


def _run(write_config, write_input, run_cli, config_map, *extra, responder=None, rows=None):
    with FakeAPIServer(responder or conversation([LOOKUP, ANSWER])) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input(rows or [ROW]), *extra)
        result.payloads = api.payloads
    return result


# Spec: "Build the initial conversation from system prompt, optional ICL
# examples, and final user prompt."
def test_first_request_carries_the_system_and_user_prompt(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    assert system_of(result.payloads[0]).startswith("Solve the math problem")
    assert user_of(result.payloads[0]) == ROW["question"]


# Spec: "Build the initial conversation from system prompt, optional ICL
# examples, and final user prompt."
def test_icl_examples_precede_the_row_question(write_config, write_input, run_cli):
    config_map = agentic_config("")
    config_map["task"]["icl"] = {"setups": [icl_setup("demo", "demo answer")]}
    result = _run(write_config, write_input, run_cli, config_map)

    roles = [role for role, _ in turns_of(result.payloads[0])]
    assert roles == ["system", "user", "assistant", "user"]
    assert user_of(result.payloads[0]) == ROW["question"]


# Spec: "Send an API request. In chat mode, include the task's tool
# definitions in the request body."
def test_chat_requests_carry_the_tool_definitions(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config("", tools=(LOOKUP_TOOL,)))

    declaration = tools_of(result.payloads[0])[0]
    assert json.dumps(declaration).count("lookup") >= 1
    assert "Look up a value in the database by key" in json.dumps(declaration)
    assert "key" in json.dumps(declaration)


# Spec: "In chat mode, include the task's tool definitions in the request
# body." - every request of the loop, not only the first
def test_tool_definitions_are_sent_on_every_iteration(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    assert len(result.payloads) == 2
    assert all(tools_of(payload) for payload in result.payloads)


# Spec: "If the response contains `tool_calls`, execute every tool call,
# append the assistant tool-call message and the tool result messages to the
# conversation ... and continue."
def test_tool_result_is_appended_before_the_next_request(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    roles = [role for role, _ in turns_of(result.payloads[1])]
    assert roles == ["system", "user", "assistant", "tool"]
    assert tool_results_of(result.payloads[1]) == ["142"]


# Spec: "parse `function.arguments` as JSON before invoking the handler"
def test_arguments_are_parsed_before_the_handler_runs(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    call = result.rows[0]["result"]["tool_calls"][0]
    assert call["args"] == {"key": "employees"}
    assert call["result"] == "142"


# Spec: "If the response contains final text and no tool calls, stop and use
# that text as the output."
def test_final_text_stops_the_loop(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    assert len(result.payloads) == 2
    assert result.rows[0]["output"] == {"answer": ANSWER}


# Spec: "if one model response contains multiple tool calls, execute and
# record all of them for that iteration"
def test_multiple_tool_calls_in_one_response_all_run(write_config, write_input, run_cli):
    both = [("lookup", {"key": "revenue_q1"}), ("lookup", {"key": "revenue_q2"})]
    result = _run(
        write_config, write_input, run_cli, agentic_config(""),
        responder=conversation([both, "Total: 2730000"]),
    )

    calls = result.rows[0]["result"]["tool_calls"]
    assert [call["args"]["key"] for call in calls] == ["revenue_q1", "revenue_q2"]
    assert [call["result"] for call in calls] == ["1250000", "1480000"]
    assert [call["iteration"] for call in calls] == [1, 1]
    assert tool_results_of(result.payloads[1]) == ["1250000", "1480000"]


# Spec: "each API request inside the loop counts separately toward request
# totals"
def test_every_loop_request_counts_in_the_summary(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli, agentic_config(""),
        responder=conversation([LOOKUP, LOOKUP, ANSWER]),
    )

    assert result.summary["total_api_calls"] == 3


# Spec: "If `max_iterations` is reached first, output `null`"
def test_max_iterations_stops_the_loop(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli, agentic_config("", max_iterations=3),
        responder=conversation([LOOKUP]),
    )

    assert len(result.payloads) == 3
    assert result.rows[0]["output"] is None


# Spec: "if the model keeps requesting tools and never produces final text /
# stop at max_iterations" - the row is a failure in the summary
def test_max_iterations_row_counts_as_failed(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli, agentic_config("", max_iterations=2),
        responder=conversation([LOOKUP]),
    )

    assert result.summary["failed"] == 1
    assert result.rows[0]["result"]["passed"] is False


# Spec: "evaluation runs against the final text output only"
def test_evaluation_reads_the_final_text_not_the_tool_results(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli, agentic_config(""),
        responder=conversation([[("lookup", {"key": "revenue_q1"})], "The answer is 142."]),
    )

    assert result.rows[0]["result"]["extracted_answer"] == "142"
    assert result.rows[0]["result"]["passed"] is True


# Spec: "echo: return the parsed tool arguments as a JSON string"
def test_a_second_declared_tool_is_reachable(write_config, write_input, run_cli):
    config_map = agentic_config("", tools=(LOOKUP_TOOL, CALCULATE_TOOL))
    result = _run(
        write_config, write_input, run_cli, config_map,
        responder=conversation([[("calculate", {"expression": "1+1"})], ANSWER]),
    )

    call = result.rows[0]["result"]["tool_calls"][0]
    assert call["tool"] == "calculate"
    assert json.loads(call["result"]) == {"expression": "1+1"}


# Spec: "a single agentic run may span many API requests, but other inputs
# must still be able to make progress concurrently ... do not fully serialize
# short batches"
@pytest.mark.slow
def test_rows_overlap_while_their_loops_run(write_config, write_input, run_cli):
    rows = [{"question": f"q{index}", "answer": "142"} for index in range(3)]
    slow = conversation([LOOKUP, ANSWER])

    with FakeAPIServer(lambda payload, index: Reply(slow(payload, index).body, delay=0.3)) as api:
        config_map = agentic_config(api.url)
        run_cli(write_config(config_map), write_input(rows))
        peak = api.peak_in_flight

    assert peak >= 2
