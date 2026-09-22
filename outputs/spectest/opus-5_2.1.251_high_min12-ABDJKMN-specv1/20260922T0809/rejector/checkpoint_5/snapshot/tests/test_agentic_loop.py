"""Spec section: Part 4 / Agentic Generation (the loop)."""
from __future__ import annotations

import json

from conftest import (AGENTIC_ROW, CALC_TOOL, COT_SETUP, LOOKUP_TOOL,
                      agentic_config, agentic_replies, tool_messages)
from mock_server import MockAPI, completion, tool_call_completion


FINAL = "The total revenue for Q1 and Q2 is 2730000."
LOOKUP_Q1 = [("lookup", {"key": "revenue_q1"})]
LOOKUP_BOTH = [("lookup", {"key": "revenue_q1"}),
               ("lookup", {"key": "revenue_q2"})]


def roles(request):
    return [m.get("role") for m in request["messages"]]


# ---------------------------------------------------------------------------
# Phrase: "1. Build the initial conversation from system prompt, optional ICL
#          examples, and final user prompt."
# Context: Part 4 / Agentic loop.
# ---------------------------------------------------------------------------
def test_initial_conversation_is_system_then_user(run_tool, write_config,
                                                  write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        first = api.requests[0]
    assert res.returncode == 0, res
    assert roles(first) == ["system", "user"]
    assert first["messages"][1]["content"] == AGENTIC_ROW["question"]


# Context: same phrase - ICL examples sit between the system and final user
# message.
def test_initial_conversation_includes_icl_examples(run_tool, write_config,
                                                    write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL],
                                          icl={"setups": [COT_SETUP]}))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        first = api.requests[0]
    assert res.returncode == 0, res
    assert roles(first) == ["system", "user", "assistant", "user", "assistant",
                            "user"]
    assert first["messages"][-1]["content"] == AGENTIC_ROW["question"]


# ---------------------------------------------------------------------------
# Phrase: "2. Send an API request. In chat mode, include the task's tool
#          definitions in the request body."
# Context: Part 4 / Agentic loop.
# ---------------------------------------------------------------------------
def test_tool_definitions_are_sent_in_the_request_body(run_tool, write_config,
                                                       write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL, CALC_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        body = api.requests[0]
    assert res.returncode == 0, res
    tools = body["tools"]
    assert [t["function"]["name"] for t in tools] == ["lookup", "calculate"]
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["description"] == LOOKUP_TOOL["description"]
    assert tools[0]["function"]["parameters"] == LOOKUP_TOOL["parameters"]
    # the handler is a local concern and is not sent to the model
    assert "handler" not in tools[0]["function"]


# Context: same phrase - every request of the loop carries the definitions.
def test_tool_definitions_are_sent_on_every_iteration(run_tool, write_config,
                                                      write_input):
    with MockAPI(agentic_replies([LOOKUP_Q1, FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        bodies = list(api.requests)
    assert res.returncode == 0, res
    assert len(bodies) == 2
    assert all("tools" in b for b in bodies)


# ---------------------------------------------------------------------------
# Phrase: "3. If the response contains `tool_calls`, execute every tool call,
#          append the assistant tool-call message and the tool result messages
#          to the conversation, ... and continue."
# Context: Part 4 / Agentic loop.
# ---------------------------------------------------------------------------
def test_assistant_and_tool_messages_are_appended(run_tool, write_config,
                                                  write_input):
    with MockAPI(agentic_replies([LOOKUP_Q1, FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        second = api.requests[1]
    assert res.returncode == 0, res
    assert roles(second) == ["system", "user", "assistant", "tool"]
    assistant = second["messages"][2]
    assert assistant["tool_calls"][0]["function"]["name"] == "lookup"
    assert second["messages"][3] == {"role": "tool", "tool_call_id": "call_1",
                                     "content": "1250000"}


# Context: same phrase - the conversation grows, it is not rebuilt from
# scratch, so round two still carries round one's messages.
def test_conversation_accumulates_across_iterations(run_tool, write_config,
                                                    write_input):
    script = [LOOKUP_Q1, [("lookup", {"key": "revenue_q2"})], FINAL]
    with MockAPI(agentic_replies(script)) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        third = api.requests[2]
    assert res.returncode == 0, res
    assert roles(third) == ["system", "user", "assistant", "tool",
                            "assistant", "tool"]
    assert [m["content"] for m in tool_messages(third)] == ["1250000",
                                                            "1480000"]


# ---------------------------------------------------------------------------
# Phrase: "if one model response contains multiple tool calls, execute and
#          record all of them for that iteration"
# Context: Part 4 / Rules.
# ---------------------------------------------------------------------------
def test_multiple_tool_calls_in_one_response(run_tool, write_config,
                                             write_input):
    with MockAPI(agentic_replies([LOOKUP_BOTH, FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        second = api.requests[1]
    assert res.returncode == 0, res
    assert [m["content"] for m in tool_messages(second)] == ["1250000",
                                                             "1480000"]
    assert [m["tool_call_id"] for m in tool_messages(second)] == ["call_1",
                                                                  "call_2"]
    recorded = res.rows[0]["result"]["tool_calls"]
    assert [(c["iteration"], c["tool"], c["args"], c["result"])
            for c in recorded] == [
        (1, "lookup", {"key": "revenue_q1"}, "1250000"),
        (1, "lookup", {"key": "revenue_q2"}, "1480000"),
    ]


# ---------------------------------------------------------------------------
# Phrase: "4. If the response contains final text and no tool calls, stop and
#          use that text as the output."
# Context: Part 4 / Agentic loop.
# ---------------------------------------------------------------------------
def test_final_text_stops_the_loop(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([LOOKUP_Q1, FINAL, "never sent"])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 2
    assert res.rows[0]["output"] == {"answer": FINAL}
    assert res.rows[0]["meta"]["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# Phrase: "5. If `max_iterations` is reached first, output `null` and use
#          `finish_reason: \"max_iterations\"`."
# Context: Part 4 / Agentic loop and the max-iteration failure example.
# ---------------------------------------------------------------------------
def test_max_iterations_stops_the_loop(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([LOOKUP_Q1])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL],
                                          max_iterations=3))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 3
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"]["iterations"] == 3
    assert row["meta"]["finish_reason"] == "max_iterations"


# Context: same phrase - `max_iterations` caps the number of API requests in
# the loop (AMBIGUITIES T61), and defaults to 10 when unset (T60).
def test_max_iterations_defaults_to_ten(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([LOOKUP_Q1])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL],
                                          max_iterations=None))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 10
    assert res.rows[0]["result"]["iterations"] == 10


# ---------------------------------------------------------------------------
# Phrase: "each API request inside the loop counts separately toward request
#          totals"
# Context: Part 4 / Rules.
# ---------------------------------------------------------------------------
def test_every_loop_request_counts_in_the_summary(run_tool, write_config,
                                                  write_input):
    script = [LOOKUP_Q1, [("lookup", {"key": "revenue_q2"})], FINAL]
    with MockAPI(agentic_replies(script)) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW, dict(AGENTIC_ROW)])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 6
    assert res.summary["total_api_calls"] == 6


# ---------------------------------------------------------------------------
# Phrase: "a single agentic run may span many API requests, but other inputs
#          must still be able to make progress concurrently" / "do not fully
#          serialize short batches"
# Context: Part 4 / Rules.
# ---------------------------------------------------------------------------
def test_rows_overlap_in_flight(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([LOOKUP_Q1, FINAL]), delay=0.2) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        rows = [{"question": f"q{i}", "answer": "2730000"} for i in range(3)]
        data = write_input(rows)
        res = run_tool(cfg, data)
        peak = api.max_inflight
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 6
    # three rows x two sequential requests: a serialized implementation would
    # never have more than one request in flight
    assert peak == 3, f"rows did not overlap in flight (peak={peak})"


# ---------------------------------------------------------------------------
# Phrase: "If the response contains final text and no tool calls"
# Context: Part 4 / Agentic loop step 4 - a response carrying BOTH text and
#          tool calls is a tool-call iteration (AMBIGUITIES T93).
# ---------------------------------------------------------------------------
def test_text_alongside_tool_calls_is_not_the_final_answer(run_tool,
                                                           write_config,
                                                           write_input):
    def responder(req, i):
        if i == 0:
            return 200, tool_call_completion(LOOKUP_Q1,
                                             content="let me look that up")
        return 200, completion(FINAL)

    with MockAPI(responder) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 2
    assert res.rows[0]["output"] == {"answer": FINAL}
