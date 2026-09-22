"""Checkpoint 4 agentic loop: conversation construction, tool execution and
termination."""

import json

from conftest import agentic_config
from fake_api import (FakeAPI, agentic, calls, final, Step, tool_call,
                      tool_completion, completion)


ROW = [{"question": "What is the total revenue for Q1 and Q2?",
        "answer": "2730000"}]


# "1. Build the initial conversation from system prompt, optional ICL
#  examples, and final user prompt."
def test_initial_conversation_is_system_then_user(run_agentic):
    with FakeAPI(agentic([final("2730000")])) as server:
        run_agentic(server, rows=ROW, check=0)
    first = server.requests[0]
    assert first.roles == ["system", "user"]
    assert first.system_content.startswith("You are a data analysis assistant")
    assert first.user_content == ROW[0]["question"]


def test_initial_conversation_includes_icl_examples(run_agentic):
    icl = {"setups": [{"name": "two_shot", "examples": [
        {"input": {"question": "ex1"}, "output": "ans1"},
        {"input": {"question": "ex2"}, "output": "ans2"}]}]}
    with FakeAPI(agentic([final("2730000")])) as server:
        run_agentic(server, task={"icl": icl}, rows=ROW, check=0)
    first = server.requests[0]
    assert first.roles == ["system", "user", "assistant", "user", "assistant",
                           "user"]
    assert first.assistant_contents == ["ans1", "ans2"]
    assert first.user_contents[-1] == ROW[0]["question"]


# "2. Send an API request.  In chat mode, include the task's tool definitions
#  in the request body."
def test_chat_requests_carry_the_tool_definitions(run_agentic):
    with FakeAPI(agentic([final("2730000")])) as server:
        run_agentic(server, rows=ROW, check=0)
    tools = server.requests[0].tools
    assert [t["type"] for t in tools] == ["function", "function"]
    assert [t["function"]["name"] for t in tools] == ["lookup", "calculate"]
    lookup = tools[0]["function"]
    assert lookup["description"] == "Look up a value in the database by key"
    assert lookup["parameters"] == agentic_config()["tools"][0]["parameters"]


def test_tool_definitions_are_sent_on_every_iteration(run_agentic):
    with FakeAPI(agentic([calls(("lookup", {"key": "employees"})),
                          final("142")])) as server:
        run_agentic(server, rows=[{"question": "q", "answer": "142"}],
                    check=0)
    assert all(r.tool_names == ["lookup", "calculate"] for r in server.requests)


def test_handler_config_is_not_sent_to_the_api(run_agentic):
    # `handler` is local execution config, not part of the OpenAI tool schema.
    with FakeAPI(agentic([final("2730000")])) as server:
        run_agentic(server, rows=ROW, check=0)
    body = json.dumps(server.requests[0].tools)
    assert "handler" not in body and "static_map" not in body


# "3. If the response contains `tool_calls`, execute every tool call, append
#  the assistant tool-call message and the tool result messages to the
#  conversation, ... and continue."
def test_tool_call_message_and_results_are_appended(run_agentic):
    script = [calls(("lookup", {"key": "revenue_q1"})), final("1250000")]
    with FakeAPI(agentic(script)) as server:
        run_agentic(server, rows=ROW, check=0)
    second = server.requests[1]
    assert second.roles == ["system", "user", "assistant", "tool"]
    assistant = second.messages[2]
    assert assistant["tool_calls"][0]["function"]["name"] == "lookup"
    assert second.messages[3]["content"] == "1250000"
    assert second.messages[3]["tool_call_id"] == \
        assistant["tool_calls"][0]["id"]


def test_the_original_prompt_is_kept_across_iterations(run_agentic):
    script = [calls(("lookup", {"key": "revenue_q1"})),
              calls(("lookup", {"key": "revenue_q2"})), final("2730000")]
    with FakeAPI(agentic(script)) as server:
        run_agentic(server, rows=ROW, check=0)
    third = server.requests[2]
    assert third.roles == ["system", "user", "assistant", "tool",
                           "assistant", "tool"]
    assert third.user_contents == [ROW[0]["question"]]
    assert [m["content"] for m in third.tool_messages] == ["1250000", "1480000"]


# "if one model response contains multiple tool calls, execute and record all
#  of them for that iteration"
def test_multiple_tool_calls_in_one_response(run_agentic):
    script = [calls(("lookup", {"key": "revenue_q1"}),
                    ("lookup", {"key": "revenue_q2"})),
              final("2730000")]
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, rows=ROW, check=0)
    recorded = res.rows[0]["result"]["tool_calls"]
    assert [c["args"] for c in recorded] == [{"key": "revenue_q1"},
                                             {"key": "revenue_q2"}]
    assert [c["result"] for c in recorded] == ["1250000", "1480000"]
    assert [c["iteration"] for c in recorded] == [1, 1]
    second = server.requests[1]
    assert second.roles == ["system", "user", "assistant", "tool", "tool"]


def test_multiple_tool_results_map_to_their_call_ids(run_agentic):
    script = [calls(("lookup", {"key": "revenue_q1"}),
                    ("calculate", {"expression": "1+1"})),
              final("2")]
    with FakeAPI(agentic(script)) as server:
        run_agentic(server, rows=ROW, check=0)
    second = server.requests[1]
    ids = [c["id"] for c in second.messages[2]["tool_calls"]]
    assert [m["tool_call_id"] for m in second.tool_messages] == ids


# "parse `function.arguments` as JSON before invoking the handler"
def test_arguments_are_parsed_from_the_json_string(run_agentic):
    def responder(rec):
        if rec.turn_index == 0:
            return 200, tool_completion([tool_call(
                "lookup", '{"key": "employees"}')])
        return 200, completion("142")
    with FakeAPI(responder) as server:
        res = run_agentic(server, rows=[{"question": "q", "answer": "142"}],
                          check=0)
    recorded = res.rows[0]["result"]["tool_calls"][0]
    assert recorded["args"] == {"key": "employees"}     # parsed, not a string
    assert recorded["result"] == "142"


def test_unknown_tool_name_is_reported_back_to_the_model(run_agentic):
    script = [calls(("nosuchtool", {"key": "x"})), final("0")]
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, rows=[{"question": "q", "answer": "0"}],
                          check=0)
        second = server.requests[1]
    recorded = res.rows[0]["result"]["tool_calls"][0]
    assert recorded["tool"] == "nosuchtool"
    assert recorded["result"].startswith("ERROR")
    assert second.tool_messages[0]["content"].startswith("ERROR")


def test_unparseable_arguments_are_reported_back_to_the_model(run_agentic):
    def responder(rec):
        if rec.turn_index == 0:
            return 200, tool_completion([tool_call("lookup", "{not json")])
        return 200, completion("0")
    with FakeAPI(responder) as server:
        res = run_agentic(server, rows=[{"question": "q", "answer": "0"}],
                          check=0)
    recorded = res.rows[0]["result"]["tool_calls"][0]
    assert recorded["result"].startswith("ERROR")
    assert res.rows[0]["result"]["iterations"] == 2


# "4. If the response contains final text and no tool calls, stop and use that
#  text as the output."
def test_final_text_stops_the_loop(run_agentic):
    with FakeAPI(agentic([final("The answer is 142.")])) as server:
        res = run_agentic(server, rows=[{"question": "q", "answer": "142"}],
                          check=0)
    assert server.call_count == 1
    assert res.rows[0]["output"] == {"answer": "The answer is 142."}


def test_loop_stops_at_the_first_text_only_response(run_agentic):
    script = [calls(("lookup", {"key": "employees"})), final("142"),
              final("never sent")]
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, rows=[{"question": "q", "answer": "142"}],
                          check=0)
    assert server.call_count == 2
    assert res.rows[0]["output"] == {"answer": "142"}


# "5. If `max_iterations` is reached first, output `null` and use
#  `finish_reason: "max_iterations"`."
def test_max_iterations_stops_the_loop(run_agentic):
    forever = [calls(("lookup", {"key": "employees"}))]
    with FakeAPI(agentic(forever)) as server:
        res = run_agentic(server,
                          task={"generation": {"scheme": "agentic",
                                               "max_iterations": 3,
                                               "temperature": 0.0,
                                               "max_tokens": 512}},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    assert server.call_count == 3
    row = res.rows[0]
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 3


def test_max_iterations_of_one_allows_a_single_request(run_agentic):
    with FakeAPI(agentic([final("142")])) as server:
        res = run_agentic(server,
                          task={"generation": {"scheme": "agentic",
                                               "max_iterations": 1,
                                               "temperature": 0.0,
                                               "max_tokens": 512}},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    assert server.call_count == 1
    assert res.rows[0]["output"] == {"answer": "142"}
    assert res.rows[0]["meta"]["finish_reason"] == "stop"


# "each API request inside the loop counts separately toward request totals"
def test_every_loop_request_counts_in_the_summary(run_agentic):
    script = [calls(("lookup", {"key": "revenue_q1"})),
              calls(("lookup", {"key": "revenue_q2"})), final("2730000")]
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, rows=ROW, check=0)
    assert server.call_count == 3
    assert res.summary["total_api_calls"] == 3
    assert res.summary["tasks"]["data_lookup"]["total_api_calls"] == 3


def test_loop_requests_count_per_task_across_rows(run_agentic):
    rows = [{"question": "q1", "answer": "142"},
            {"question": "q2", "answer": "142"}]
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, rows=rows, check=0)
    assert res.summary["total_api_calls"] == 4


# The usual 5xx retry rule still applies to each request inside the loop.
def test_a_5xx_inside_the_loop_is_retried(run_agentic):
    def responder(rec):
        # first request: tool call; then two 500s, then the final text
        if rec.turn_index == 0:
            return 200, tool_completion([tool_call("lookup",
                                                   {"key": "employees"})])
        if rec.index in (1, 2):
            return 500, {"error": {"message": "boom"}}
        return 200, completion("142")
    with FakeAPI(responder) as server:
        res = run_agentic(server, rows=[{"question": "q", "answer": "142"}],
                          check=0)
    assert res.rows[0]["output"] == {"answer": "142"}
    # iterations counts logical requests, not HTTP retries
    assert res.rows[0]["result"]["iterations"] == 2
