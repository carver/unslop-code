"""The agentic loop: tool calls, the growing conversation, and its bounds."""

from __future__ import annotations

from conftest import CALCULATE_TOOL, agentic_config, icl_setup, turn_responder
from mock_server import Reply

ROW = [{"question": "How many employees?", "answer": "142"}]
LOOKUP = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "employees"}}])
ANSWER = Reply(content="The company has 142 employees.")


def lookup_then_answer():
    return turn_responder(LOOKUP, ANSWER)


# Spec: "Send an API request. In chat mode, include the task's tool definitions
# in the request body."
def test_chat_request_carries_the_tool_definitions(servers, run_cli):
    server = servers(responder=lookup_then_answer())
    result = run_cli(agentic_config(server.url), ROW)
    assert result.exit_code == 0, result.stderr
    assert server.payloads[0]["tools"][0] == {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Look up a value in the database by key",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The database key to look up",
                    }
                },
                "required": ["key"],
            },
        },
    }


# Spec: "Build the initial conversation from system prompt, optional ICL
# examples, and final user prompt."
def test_initial_conversation_is_system_then_user(servers, run_cli):
    server = servers(responder=lookup_then_answer())
    run_cli(agentic_config(server.url), ROW)
    messages = server.payloads[0]["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[1]["content"] == "How many employees?"


# Spec: "Build the initial conversation from system prompt, optional ICL
# examples, and final user prompt."
def test_initial_conversation_includes_icl_examples(servers, run_cli):
    server = servers(responder=lookup_then_answer())
    config = agentic_config(
        server.url, icl={"setups": [icl_setup("direct", "142")]}
    )
    run_cli(config, ROW)
    roles = [message["role"] for message in server.payloads[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


# Spec: "If the response contains `tool_calls`, execute every tool call, append
# the assistant tool-call message and the tool result messages to the
# conversation, increment the iteration count, and continue."
def test_tool_result_is_appended_to_the_conversation(servers, run_cli):
    server = servers(responder=lookup_then_answer())
    result = run_cli(agentic_config(server.url), ROW)
    assert result.exit_code == 0, result.stderr
    messages = server.payloads[1]["messages"]
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert messages[2]["tool_calls"][0]["function"]["name"] == "lookup"
    assert messages[3]["content"] == "142"
    assert messages[3]["tool_call_id"] == messages[2]["tool_calls"][0]["id"]


# Spec: "If the response contains final text and no tool calls, stop and use
# that text as the output."
def test_final_text_ends_the_loop(servers, run_cli):
    server = servers(responder=lookup_then_answer())
    result = run_cli(agentic_config(server.url), ROW)
    assert server.call_count == 2
    assert result.rows[0]["output"] == {"answer": "The company has 142 employees."}


# Spec: "parse `function.arguments` as JSON before invoking the handler" -- the
# handler sees the decoded key, and the record stores the decoded arguments.
def test_arguments_are_parsed_as_json(servers, run_cli):
    server = servers(responder=lookup_then_answer())
    result = run_cli(agentic_config(server.url), ROW)
    assert result.rows[0]["result"]["tool_calls"][0] == {
        "iteration": 1,
        "tool": "lookup",
        "args": {"key": "employees"},
        "result": "142",
    }


# Spec: "if one model response contains multiple tool calls, execute and record
# all of them for that iteration".
def test_multiple_tool_calls_in_one_response(servers, run_cli):
    both = Reply(
        tool_calls=[
            {"name": "lookup", "arguments": {"key": "revenue_q1"}},
            {"name": "lookup", "arguments": {"key": "revenue_q2"}},
        ]
    )
    server = servers(responder=turn_responder(both, Reply(content="Total is 2730000")))
    rows = [{"question": "Total revenue?", "answer": "2730000"}]
    result = run_cli(agentic_config(server.url), rows)
    assert result.exit_code == 0, result.stderr
    recorded = result.rows[0]["result"]["tool_calls"]
    assert [call["iteration"] for call in recorded] == [1, 1]
    assert [call["result"] for call in recorded] == ["1250000", "1480000"]
    assert len(server.payloads[1]["messages"]) == 5


# Spec: "execute every tool call, append ... the tool result messages" -- a
# `static_map` miss feeds its default back to the model.
def test_unmapped_key_feeds_back_the_default(servers, run_cli):
    miss = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "headcount"}}])
    server = servers(responder=turn_responder(miss, ANSWER))
    run_cli(agentic_config(server.url), ROW)
    assert server.payloads[1]["messages"][3]["content"] == "KEY_NOT_FOUND"


# Spec: "If `max_iterations` is reached first, output `null` and use
# `finish_reason: \"max_iterations\"`."
def test_max_iterations_stops_the_loop(servers, run_cli):
    server = servers(responder=turn_responder(LOOKUP))
    config = agentic_config(server.url, generation={"max_iterations": 3})
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 3
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"]["iterations"] == 3
    assert row["meta"]["finish_reason"] == "max_iterations"


# Spec: "each API request inside the loop counts separately toward request
# totals".
def test_every_request_counts_toward_the_totals(servers, run_cli):
    server = servers(responder=lookup_then_answer())
    rows = [{"question": f"q{index}", "answer": "142"} for index in range(3)]
    result = run_cli(agentic_config(server.url), rows)
    assert result.summary["total_api_calls"] == 6
    assert result.summary["tasks"]["gsm8k_solve"]["total_api_calls"] == 6


# Spec: tools are addressed by name -- a task with two tools routes each call
# to the handler that owns it.
def test_calls_are_routed_by_tool_name(servers, run_cli):
    calculate = Reply(
        tool_calls=[{"name": "calculate", "arguments": {"expression": "1+1"}}]
    )
    server = servers(responder=turn_responder(calculate, ANSWER))
    config = agentic_config(server.url, tools=[CALCULATE_TOOL])
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert result.rows[0]["result"]["tool_calls"][0]["result"] == '{"expression": "1+1"}'
