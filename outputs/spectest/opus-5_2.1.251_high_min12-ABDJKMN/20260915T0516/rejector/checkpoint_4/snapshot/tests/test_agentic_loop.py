"""Part 4: the agentic loop — tool definitions, tool execution, iterations."""
import pytest

from conftest import (agentic_config, assistant_tool_calls, echo_tool,
                      icl_block, marker_setups, static_map_tool, tool_messages)
from mock_api import MockAPI, agentic_turns, always, chat_response

ROWS = [{"question": "How many employees are there?", "answer": "142"}]
REVENUE = [{"question": "What is the total revenue for Q1 and Q2?",
            "answer": "2730000"}]


# Spec: "Extend the pipeline with an `agentic` generation mode."
#       `scheme: "agentic"` in the task's generation block.
# Context: Agentic Generation, task example.
def test_agentic_scheme_is_accepted(run_tool):
    with MockAPI(always("The company has 142 employees.")) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["output"] == {"answer": "The company has 142 employees."}


# Spec: "Send an API request. In chat mode, include the task's tool
#        definitions in the request body."
# Context: Agentic loop step 2.
def test_chat_requests_carry_the_tool_definitions(run_tool):
    with MockAPI(always("142 employees.")) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    tools = api.calls[0]["tools"]
    assert [t["function"]["name"] for t in tools] == ["lookup", "calculate"]
    assert tools[0] == {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Look up a value in the database by key",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string",
                                       "description": "The database key to "
                                                      "look up"}},
                "required": ["key"],
            },
        },
    }


def test_every_request_in_the_loop_carries_the_tools(run_tool):
    steps = [[("lookup", {"key": "employees"})], "142 employees."]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    assert len(api.calls) == 2
    assert all("tools" in payload for payload in api.calls)


# Spec: a non-agentic task has no tool definitions to send.
def test_non_agentic_requests_have_no_tools_field(run_tool):
    from conftest import make_config
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   tools=[static_map_tool()]), ROWS)
    assert run.returncode == 0, run.stderr
    assert "tools" not in api.calls[0]


# Spec: "If the response contains `tool_calls`, execute every tool call,
#        append the assistant tool-call message and the tool result messages
#        to the conversation, increment the iteration count, and continue."
# Context: Agentic loop step 3.
def test_tool_result_is_appended_to_the_next_request(run_tool):
    steps = [[("lookup", {"key": "employees"})], "The company has 142."]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    second = api.calls[1]
    assert [m["content"] for m in tool_messages(second)] == ["142"]


def test_assistant_tool_call_message_is_appended_to_the_conversation(run_tool):
    steps = [[("lookup", {"key": "employees"})], "The company has 142."]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    calls = assistant_tool_calls(api.calls[1])
    assert len(calls) == 1
    assert calls[0]["role"] == "assistant"
    assert calls[0]["tool_calls"][0]["function"]["name"] == "lookup"


def test_tool_message_links_back_to_its_call_id(run_tool):
    steps = [[("lookup", {"key": "employees"})], "The company has 142."]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    second = api.calls[1]
    call_id = assistant_tool_calls(second)[0]["tool_calls"][0]["id"]
    assert tool_messages(second)[0]["tool_call_id"] == call_id


def test_conversation_grows_across_iterations(run_tool):
    steps = [[("lookup", {"key": "revenue_q1"})],
             [("lookup", {"key": "revenue_q2"})],
             "The total is 2730000."]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), REVENUE)
    assert run.returncode == 0, run.stderr
    lengths = [len(payload["messages"]) for payload in api.calls]
    assert lengths == [2, 4, 6]
    assert [m["content"] for m in tool_messages(api.calls[2])] == ["1250000",
                                                                  "1480000"]


# Spec: "If the response contains final text and no tool calls, stop and use
#        that text as the output."
# Context: Agentic loop step 4.
def test_loop_stops_on_final_text(run_tool):
    steps = [[("lookup", {"key": "employees"})], "The company has 142.", "MORE"]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    assert len(api.calls) == 2
    assert run.rows[0]["output"] == {"answer": "The company has 142."}


# Spec: "parse `function.arguments` as JSON before invoking the handler"
# Context: Rules, chat tool-call shape.
def test_function_arguments_are_parsed_as_json(run_tool):
    steps = [[("lookup", '{"key": "revenue_q1"}')], "It is 1250000."]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), REVENUE)
    assert run.returncode == 0, run.stderr
    recorded = run.rows[0]["result"]["tool_calls"][0]
    assert recorded["args"] == {"key": "revenue_q1"}
    assert recorded["result"] == "1250000"


# Spec: "if one model response contains multiple tool calls, execute and
#        record all of them for that iteration"
# Context: Rules.
def test_multiple_tool_calls_in_one_response_all_execute(run_tool):
    steps = [[("lookup", {"key": "revenue_q1"}),
              ("lookup", {"key": "revenue_q2"})],
             "The total revenue for Q1 and Q2 is $2,730,000."]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), REVENUE)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
         "result": "1250000"},
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"},
         "result": "1480000"},
    ]
    assert len(tool_messages(api.calls[1])) == 2


def test_multiple_tool_calls_count_as_one_iteration(run_tool):
    steps = [[("lookup", {"key": "revenue_q1"}),
              ("lookup", {"key": "revenue_q2"})], "Total 2730000."]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), REVENUE)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["iterations"] == 2


# Spec: "If `max_iterations` is reached first, output `null` and use
#        `finish_reason: "max_iterations"`."
# Context: Agentic loop step 5 / Max-iteration failure example.
def test_max_iterations_stops_the_loop_with_null_output(run_tool):
    steps = [[("lookup", {"key": "employees"})]]        # never finishes
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url, max_iterations=3), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert len(api.calls) == 3
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 3


def test_max_iterations_defaults_to_ten(run_tool):
    steps = [[("lookup", {"key": "employees"})]]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url, max_iterations=None), ROWS)
    assert run.returncode == 0, run.stderr
    assert len(api.calls) == 10
    assert run.rows[0]["result"]["iterations"] == 10


# Spec: "each API request inside the loop counts separately toward request
#        totals"
# Context: Rules.
def test_every_loop_request_counts_in_the_summary(run_tool):
    steps = [[("lookup", {"key": "revenue_q1"})],
             [("lookup", {"key": "revenue_q2"})], "2730000"]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), REVENUE)
    assert run.returncode == 0, run.stderr
    assert run.summary["total_api_calls"] == 3
    assert run.summary["total_prompt_tokens"] == 3 * 45
    assert run.summary["total_completion_tokens"] == 3 * 120


# Spec: "Build the initial conversation from system prompt, optional ICL
#        examples, and final user prompt."
# Context: Agentic loop step 1.
def test_initial_conversation_is_system_then_user(run_tool):
    with MockAPI(always("142")) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    roles = [m["role"] for m in api.calls[0]["messages"]]
    assert roles == ["system", "user"]
    assert api.calls[0]["messages"][1]["content"] == ROWS[0]["question"]


def test_initial_conversation_includes_icl_examples(run_tool):
    icl = icl_block(marker_setups(["chain_of_thought"]))
    with MockAPI(always("142")) as api:
        run = run_tool(agentic_config(api.url, icl=icl), ROWS)
    assert run.returncode == 0, run.stderr
    roles = [m["role"] for m in api.calls[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert api.calls[0]["messages"][2]["content"] == "MARK_chain_of_thought0"


# Spec: "a single agentic run may span many API requests, but other inputs
#        must still be able to make progress concurrently"
# Context: Rules.
def test_rows_overlap_in_flight_during_agentic_loops(run_tool):
    rows = [{"question": "q%d employees" % i, "answer": "142"}
            for i in range(6)]
    steps = [[("lookup", {"key": "employees"})], "142"]
    with MockAPI(agentic_turns(steps), service_seconds=0.2,
                 capacity_rpm=1200) as api:
        run = run_tool(agentic_config(api.url, rpm=1200), rows)
    assert run.returncode == 0, run.stderr
    assert len(api.calls) == 12
    assert api.max_concurrent > 1


# Spec: "do not fully serialize short batches; for example, if three input
#        rows are all pending and each needs a tool call followed by a final
#        answer, requests from different rows should still be able to
#        overlap in flight"
# Context: Rules.
def test_three_row_batch_is_not_serialized(run_tool):
    rows = [{"question": "row %d employees" % i, "answer": "142"}
            for i in range(3)]
    steps = [[("lookup", {"key": "employees"})], "142"]
    with MockAPI(agentic_turns(steps), service_seconds=0.25,
                 capacity_rpm=1200) as api:
        run = run_tool(agentic_config(api.url, rpm=600), rows)
    assert run.returncode == 0, run.stderr
    assert api.max_concurrent >= 3
    # Six requests at 0.25s each would take 1.5s if fully serialized.
    assert run.summary["elapsed_seconds"] < 1.0


# Spec: tools are executed by name; an unknown name still records a call.
def test_unknown_tool_name_is_recorded_with_an_error_result(run_tool):
    steps = [[("nosuchtool", {"key": "employees"})], "done"]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    recorded = run.rows[0]["result"]["tool_calls"][0]
    assert recorded["tool"] == "nosuchtool"
    assert recorded["result"].startswith("ERROR:")


# Spec: the loop ends when a request cannot be completed at all.
def test_failed_request_ends_the_loop_with_null_output(run_tool):
    steps = [[("lookup", {"key": "employees"})], 500]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["iterations"] == 1
