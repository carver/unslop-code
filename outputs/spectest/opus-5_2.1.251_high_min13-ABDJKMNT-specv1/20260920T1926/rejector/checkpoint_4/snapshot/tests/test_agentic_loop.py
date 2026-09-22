"""The agentic loop: tool turns, the conversation it builds, and its limit."""

from __future__ import annotations

import json

from conftest import agentic_task
from fake_api import FakeAPI, Reply, always, call, turns

ROW = {"question": "How many employees?", "answer": "142"}
TOTALS = {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"}

LOOKUP_EMPLOYEES = Reply(content=None, tools=(call("lookup", key="employees"),))
FINAL_EMPLOYEES = Reply(content="The company has 142 employees.")


def tool_messages(body: dict) -> list[dict]:
    return [message for message in body["messages"] if message["role"] == "tool"]


# Spec: "Build the initial conversation from system prompt, optional ICL
# examples, and final user prompt."
# Context: Agentic loop, step 1.
def test_initial_conversation_is_system_then_user(write_config, write_input, run_cli):
    with FakeAPI(responder=always("142 employees")) as api:
        run_cli(write_config(agentic_task(api.url)), write_input([ROW]))
        messages = api.requests[0]["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[1]["content"] == ROW["question"]


# Spec: "In chat mode, include the task's tool definitions in the request body."
# Context: Agentic loop, step 2.
def test_chat_requests_carry_the_tool_definitions(write_config, write_input, run_cli):
    with FakeAPI(responder=always("142 employees")) as api:
        run_cli(write_config(agentic_task(api.url)), write_input([ROW]))
        tools = api.requests[0]["tools"]
    assert [tool["function"]["name"] for tool in tools] == ["lookup", "calculate"]
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["description"] == "Look up a value in the database by key"
    assert tools[0]["function"]["parameters"]["required"] == ["key"]


# Spec: "If the response contains `tool_calls`, execute every tool call,
# append the assistant tool-call message and the tool result messages to the
# conversation, increment the iteration count, and continue."
# Context: Agentic loop, step 3.
def test_tool_results_are_appended_to_the_conversation(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP_EMPLOYEES, FINAL_EMPLOYEES])) as api:
        run_cli(write_config(agentic_task(api.url)), write_input([ROW]))
        second = api.requests[1]["messages"]
    assert [message["role"] for message in second] == ["system", "user", "assistant", "tool"]
    assert second[2]["tool_calls"][0]["function"]["name"] == "lookup"
    assert second[3]["content"] == "142"
    assert second[3]["tool_call_id"] == second[2]["tool_calls"][0]["id"]


# Spec: "If the response contains final text and no tool calls, stop and use
# that text as the output."
# Context: Agentic loop, step 4.
def test_final_text_ends_the_loop(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP_EMPLOYEES, FINAL_EMPLOYEES])) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([ROW]))
        assert api.call_count == 2
    assert result.rows[0]["output"] == {"answer": "The company has 142 employees."}
    assert result.rows[0]["meta"]["finish_reason"] == "stop"


# Spec: "if the model calls `lookup(key=\"employees\")` and the handler
# returns `\"142\"` ... `result.iterations` is `2` and `result.tool_calls`
# contains the lookup"
# Context: Examples / Simple lookup.
def test_simple_lookup_example(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP_EMPLOYEES, FINAL_EMPLOYEES])) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([ROW]))
    row = result.rows[0]
    assert row["result"]["iterations"] == 2
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]
    assert row["result"]["passed"] is True


# Spec: "parse `function.arguments` as JSON before invoking the handler"
# Context: Agentic loop / Rules.
def test_function_arguments_are_parsed_as_json(write_config, write_input, run_cli):
    calls = (call("calculate", expression="1250000 + 1480000"),)
    script = [Reply(content=None, tools=calls), Reply(content="2730000")]
    with FakeAPI(responder=turns(script)) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([TOTALS]))
        echoed = api.requests[1]["messages"][-1]["content"]
    recorded = result.rows[0]["result"]["tool_calls"][0]
    assert recorded["args"] == {"expression": "1250000 + 1480000"}
    assert json.loads(echoed) == {"expression": "1250000 + 1480000"}


# Spec: "if one model response contains multiple tool calls, execute and
# record all of them for that iteration"
# Context: Agentic loop / Rules.
def test_multiple_tool_calls_in_one_response(write_config, write_input, run_cli):
    both = (call("lookup", key="revenue_q1"), call("lookup", key="revenue_q2"))
    script = [Reply(content=None, tools=both), Reply(content="$2,730,000 in total")]
    with FakeAPI(responder=turns(script)) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([TOTALS]))
        assert len(tool_messages(api.requests[1])) == 2
    assert result.rows[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"}, "result": "1250000"},
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"}, "result": "1480000"},
    ]
    assert result.rows[0]["result"]["iterations"] == 2


# Spec: "If `max_iterations` is reached first, output `null` and use
# `finish_reason: \"max_iterations\"`."
# Context: Agentic loop, step 5 / Examples / Max-iteration failure.
def test_max_iterations_stops_the_loop(write_config, write_input, run_cli):
    with FakeAPI(responder=always(None, tools=(call("lookup", key="employees"),))) as api:
        task = agentic_task(api.url)
        task["generation"]["max_iterations"] = 3
        result = run_cli(write_config(task), write_input([ROW]))
        assert api.call_count == 3
    row = result.rows[0]
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 3


# Spec: "each API request inside the loop counts separately toward request
# totals"
# Context: Agentic loop / Rules.
def test_every_loop_request_counts_toward_the_summary(write_config, write_input, run_cli):
    script = [LOOKUP_EMPLOYEES, LOOKUP_EMPLOYEES, FINAL_EMPLOYEES]
    with FakeAPI(responder=turns(script)) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([ROW, ROW]))
        assert api.call_count == 6
    assert result.summary["total_api_calls"] == 6


# Spec: "evaluation runs against the final text output only"
# Context: Agentic Output / Rules; the tool result alone would not match.
def test_evaluation_ignores_tool_results(write_config, write_input, run_cli):
    script = [LOOKUP_EMPLOYEES, Reply(content="I could not work it out.")]
    with FakeAPI(responder=turns(script)) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([ROW]))
    assert result.rows[0]["result"]["passed"] is False
    assert result.rows[0]["result"]["extracted_answer"] is None


# Spec: "if `max_iterations` is hit, evaluation fails because output is `null`"
# Context: Agentic Output / Rules.
def test_max_iterations_fails_evaluation(write_config, write_input, run_cli):
    with FakeAPI(responder=always(None, tools=(call("lookup", key="employees"),))) as api:
        task = agentic_task(api.url)
        task["generation"]["max_iterations"] = 2
        result = run_cli(write_config(task), write_input([ROW]))
    assert result.rows[0]["result"]["passed"] is False
    assert result.summary["failed"] == 1


# Spec: "`static_map`: look up the first required parameter in `mapping`; if
# absent, return `default`"
# Context: Handler types, reached through a real loop.
def test_unknown_key_feeds_the_default_back(write_config, write_input, run_cli):
    script = [Reply(content=None, tools=(call("lookup", key="profit"),)), Reply(content="0")]
    with FakeAPI(responder=turns(script)) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([ROW]))
        assert tool_messages(api.requests[1])[0]["content"] == "KEY_NOT_FOUND"
    assert result.rows[0]["result"]["tool_calls"][0]["result"] == "KEY_NOT_FOUND"
