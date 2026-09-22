"""Tests derived phrase-by-phrase from the Part 4 (checkpoint 4) spec.

Part 4 adds the `agentic` generation scheme — a tool-calling loop with its own
row/meta shape — and `api_type: "completions"`, which renders the conversation
through one of four built-in chat templates and posts it to `/v1/completions`.

Each section comment quotes the spec phrase under test plus the minimal
context needed to read it.
"""
import copy
import json

import pytest

from conftest import (completion, make_config, make_multi_config,
                      text_completion, tool_call_completion, tool_call_text)

# ---------------------------------------------------------------------------
# Fixtures built from the spec's canonical agentic task
# ---------------------------------------------------------------------------

SYSTEM = ("You are a data analysis assistant. Use the provided tools to look "
          "up data and answer questions.")

LOOKUP_TOOL = {
    "name": "lookup",
    "description": "Look up a value in the database by key",
    "parameters": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "The database key to look up"},
        },
        "required": ["key"],
    },
    "handler": {
        "type": "static_map",
        "mapping": {
            "revenue_q1": "1250000",
            "revenue_q2": "1480000",
            "employees": "142",
        },
        "default": "KEY_NOT_FOUND",
    },
}

CALC_TOOL = {
    "name": "calculate",
    "description": "Evaluate a mathematical expression",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {"type": "string",
                           "description": "The math expression to evaluate"},
        },
        "required": ["expression"],
    },
    "handler": {"type": "echo"},
}

SPEC_TOOLS = [LOOKUP_TOOL, CALC_TOOL]

ROWS = [{"question": "What is the total revenue for Q1 and Q2?",
         "answer": "2730000"}]
EMPLOYEE_ROWS = [{"question": "How many employees are there?", "answer": "142"}]

FINAL = "The total revenue for Q1 and Q2 is $2,730,000."


def agentic_config(url, *, tools=SPEC_TOOLS, max_iterations=10, **over):
    """The spec's canonical `data_lookup` task, with overrides merged in."""
    cfg = {
        "task": {
            "name": "data_lookup",
            "api_url": url,
            "model": "gpt-4",
            "rpm": 60,
            "prompt": {"system": SYSTEM, "user": "{question}"},
            "generation": {
                "scheme": "agentic",
                "max_iterations": max_iterations,
                "temperature": 0.0,
                "max_tokens": 512,
            },
            "evaluation": {"type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"},
            "output_field": "answer",
            "tools": copy.deepcopy(tools) if tools is not None else None,
        }
    }
    for key, value in over.items():
        if value is None:
            cfg["task"].pop(key, None)
        else:
            cfg["task"][key] = value
    if cfg["task"].get("tools") is None:
        cfg["task"].pop("tools", None)
    return cfg


def is_completions(body):
    return "prompt" in body and "messages" not in body


# Rendered tool-role markers, one per built-in template: their presence in a
# completions prompt means a tool result has already been fed back.
TOOL_ROLE_MARKERS = ("<|im_start|>tool\n", "<|start_header_id|>tool<|end_header_id|>",
                     "<|tool|>\n", "[TOOL_RESULTS]")


def has_tool_result(body):
    if is_completions(body):
        return any(marker in body["prompt"] for marker in TOOL_ROLE_MARKERS)
    return any(m.get("role") == "tool" for m in body.get("messages", []))


def two_step(api, calls, final=FINAL, *, delay=0.0):
    """Answer a row's first request with `calls`, any later one with `final`.

    The decision is made from the request itself (does the conversation already
    carry a tool result?) so it stays correct when several rows are in flight.
    """
    def responder(body, index):
        if has_tool_result(body):
            payload = (text_completion(final) if is_completions(body)
                       else completion(final))
            return 200, payload
        if is_completions(body):
            return 200, text_completion(tool_call_text(calls))
        return 200, tool_call_completion(calls)
    return api(responder, delay=delay)


def always_tool(api, calls, *, delay=0.0):
    """A server that never stops asking for tools."""
    def responder(body, index):
        if is_completions(body):
            return 200, text_completion(tool_call_text(calls))
        return 200, tool_call_completion(calls)
    return api(responder, delay=delay)


LOOKUP_Q1 = [{"name": "lookup", "arguments": {"key": "revenue_q1"}}]
LOOKUP_BOTH = [{"name": "lookup", "arguments": {"key": "revenue_q1"}},
               {"name": "lookup", "arguments": {"key": "revenue_q2"}}]
LOOKUP_EMPLOYEES = [{"name": "lookup", "arguments": {"key": "employees"}}]


# ---------------------------------------------------------------------------
# Agentic Generation
# "Extend the pipeline with an `agentic` generation mode"
# "Agentic tasks let the model call tools in a loop before producing a final
#  answer."
# ---------------------------------------------------------------------------

def test_agentic_scheme_is_accepted(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert len(r.rows) == 1


def test_spec_canonical_agentic_task_runs_end_to_end(run_cli, api):
    """The exact task block from the spec, both tools declared."""
    mock = two_step(api, LOOKUP_BOTH)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] == {"answer": FINAL}
    assert row["result"]["passed"] is True


# "Existing behavior from earlier parts is unchanged unless stated here."
def test_non_agentic_tasks_are_untouched(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [{"question": "2+3?", "answer": "5"}])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}
    assert "iterations" not in row["result"]          # T89
    assert "tool_calls" not in row["result"]


def test_unknown_scheme_still_rejected(run_cli, echo_api):
    cfg = make_config(echo_api.url)
    cfg["task"]["generation"]["scheme"] = "agentix"
    r = run_cli(cfg, ROWS)
    assert r.code == 1


# "scheme: agentic / max_iterations: 10 / temperature: 0.0"  (T66)
def test_agentic_accepts_temperature_zero(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert mock.bodies[0]["temperature"] == 0.0


# T65: `max_iterations` is optional and defaults to the example's 10.
def test_max_iterations_defaults_when_omitted(run_cli, api):
    mock = always_tool(api, LOOKUP_Q1)
    cfg = agentic_config(mock.url)
    cfg["task"]["generation"].pop("max_iterations")
    r = run_cli(cfg, ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["iterations"] == 10


def test_max_iterations_must_be_a_positive_integer(run_cli, echo_api):
    r = run_cli(agentic_config(echo_api.url, max_iterations=0), ROWS)
    assert r.code == 1
    assert "max_iterations" in r.stderr


# ---------------------------------------------------------------------------
# Handler types
# "echo: return the parsed tool arguments as a JSON string"
# ---------------------------------------------------------------------------

def test_echo_handler_returns_arguments_as_json(run_cli, api):
    calls = [{"name": "calculate", "arguments": {"expression": "1250000+1480000"}}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    recorded = r.rows[0]["result"]["tool_calls"]
    assert len(recorded) == 1
    assert json.loads(recorded[0]["result"]) == {"expression": "1250000+1480000"}


def test_echo_handler_result_is_fed_back_as_a_string(run_cli, api):
    calls = [{"name": "calculate", "arguments": {"expression": "2+2"}}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    follow_up = mock.bodies[1]
    tool_msgs = [m for m in follow_up["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert isinstance(tool_msgs[0]["content"], str)
    assert json.loads(tool_msgs[0]["content"]) == {"expression": "2+2"}


# "static_map: look up the first required parameter in `mapping`"
def test_static_map_looks_up_the_first_required_parameter(run_cli, api):
    mock = two_step(api, LOOKUP_EMPLOYEES, final="The company has 142 employees.")
    r = run_cli(agentic_config(mock.url), EMPLOYEE_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["tool_calls"][0]["result"] == "142"


def test_static_map_maps_each_configured_key(run_cli, api):
    mock = two_step(api, LOOKUP_BOTH)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    results = [c["result"] for c in r.rows[0]["result"]["tool_calls"]]
    assert results == ["1250000", "1480000"]


# "if absent, return `default`"
def test_static_map_returns_configured_default_for_missing_key(run_cli, api):
    calls = [{"name": "lookup", "arguments": {"key": "profit"}}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["tool_calls"][0]["result"] == "KEY_NOT_FOUND"


# "`default`, which defaults to `\"NOT_FOUND\"`"
def test_static_map_default_default_is_not_found(run_cli, api):
    tool = copy.deepcopy(LOOKUP_TOOL)
    tool["handler"].pop("default")
    calls = [{"name": "lookup", "arguments": {"key": "profit"}}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url, tools=[tool]), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["tool_calls"][0]["result"] == "NOT_FOUND"


# "script: run `command` with the value of `arg_field` as a single
#  command-line argument, capture stdout, and return it"
SCRIPT_TOOL = {
    "name": "python",
    "description": "Run python code",
    "parameters": {
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
    },
    "handler": {"type": "script", "command": "python3 -c", "arg_field": "code"},
}


def test_script_handler_returns_stdout(run_cli, api):
    calls = [{"name": "python", "arguments": {"code": "print(1250000 + 1480000)"}}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url, tools=[SCRIPT_TOOL]), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["tool_calls"][0]["result"].strip() == "2730000"


def test_script_handler_passes_arg_field_as_one_argument(run_cli, api):
    """A single argv entry: spaces in the code must not split it."""
    calls = [{"name": "python", "arguments": {"code": "print('a b c')"}}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url, tools=[SCRIPT_TOOL]), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["tool_calls"][0]["result"].strip() == "a b c"


# "on timeout or non-zero exit, return `\"ERROR: <stderr or timeout message>\"`"
def test_script_handler_reports_non_zero_exit_as_error(run_cli, api):
    calls = [{"name": "python", "arguments": {"code": "raise SystemExit(3)"}}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url, tools=[SCRIPT_TOOL]), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["tool_calls"][0]["result"].startswith("ERROR:")


def test_script_handler_error_carries_stderr(run_cli, api):
    calls = [{"name": "python", "arguments": {"code": "raise ValueError('boom')"}}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url, tools=[SCRIPT_TOOL]), ROWS)
    assert r.code == 0, r.stderr
    result = r.rows[0]["result"]["tool_calls"][0]["result"]
    assert result.startswith("ERROR:")
    assert "boom" in result


def test_unknown_handler_type_is_a_config_error(run_cli, echo_api):
    tool = copy.deepcopy(LOOKUP_TOOL)
    tool["handler"] = {"type": "magic"}
    r = run_cli(agentic_config(echo_api.url, tools=[tool]), ROWS)
    assert r.code == 1
    assert "handler" in r.stderr


def test_script_handler_requires_command_and_arg_field(run_cli, echo_api):
    tool = copy.deepcopy(SCRIPT_TOOL)
    tool["handler"] = {"type": "script", "command": "python3 -c"}
    r = run_cli(agentic_config(echo_api.url, tools=[tool]), ROWS)
    assert r.code == 1
    assert "arg_field" in r.stderr


# ---------------------------------------------------------------------------
# Agentic loop
# "1. Build the initial conversation from system prompt, optional ICL
#     examples, and final user prompt."
# ---------------------------------------------------------------------------

def test_initial_conversation_is_system_then_user(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    messages = mock.bodies[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == SYSTEM
    assert messages[1]["content"] == ROWS[0]["question"]


# "2. Send an API request. In chat mode, include the task's tool definitions
#     in the request body."
def test_chat_requests_carry_tool_definitions(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    tools = mock.bodies[0]["tools"]
    assert [t["function"]["name"] for t in tools] == ["lookup", "calculate"]
    assert tools[0]["type"] == "function"                     # T67
    assert tools[0]["function"]["description"] == LOOKUP_TOOL["description"]
    assert tools[0]["function"]["parameters"] == LOOKUP_TOOL["parameters"]


def test_handler_config_is_not_sent_to_the_model(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert "handler" not in json.dumps(mock.bodies[0]["tools"])


def test_every_request_in_the_loop_carries_the_tools(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert len(mock.bodies) == 2
    assert all("tools" in b for b in mock.bodies)


# T84: a non-agentic task never advertises tools.
def test_non_agentic_task_does_not_send_tools(run_cli, echo_api):
    cfg = make_config(echo_api.url)
    cfg["task"]["tools"] = copy.deepcopy(SPEC_TOOLS)
    r = run_cli(cfg, [{"question": "2+3?", "answer": "5"}])
    assert r.code == 0, r.stderr
    assert "tools" not in echo_api.bodies[0]


# "3. If the response contains `tool_calls`, execute every tool call, append
#     the assistant tool-call message and the tool result messages to the
#     conversation, increment the iteration count, and continue."
def test_assistant_tool_call_message_is_appended(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    messages = mock.bodies[1]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert messages[2]["tool_calls"][0]["function"]["name"] == "lookup"


def test_tool_result_messages_carry_the_call_id(run_cli, api):
    calls = [{"name": "lookup", "arguments": {"key": "revenue_q1"},
              "id": "call_abc123"}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    tool_msg = mock.bodies[1]["messages"][-1]
    assert tool_msg["role"] == "tool"                          # T75
    assert tool_msg["tool_call_id"] == "call_abc123"
    assert tool_msg["content"] == "1250000"


def test_conversation_grows_across_iterations(run_cli, api):
    """Three tool rounds then a final answer: each round adds two messages."""
    def responder(body, index):
        messages = body["messages"]
        rounds = sum(1 for m in messages if m.get("role") == "tool")
        if rounds >= 3:
            return 200, completion(FINAL)
        return 200, tool_call_completion(LOOKUP_Q1)
    mock = api(responder)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    lengths = [len(b["messages"]) for b in mock.bodies]
    assert lengths == [2, 4, 6, 8]
    assert r.rows[0]["result"]["iterations"] == 4


# "4. If the response contains final text and no tool calls, stop and use that
#     text as the output."
def test_final_text_stops_the_loop(run_cli, api):
    mock = api(lambda body, i: (200, completion(FINAL)))
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 1
    assert r.rows[0]["output"] == {"answer": FINAL}
    assert r.rows[0]["result"]["iterations"] == 1
    assert r.rows[0]["result"]["tool_calls"] == []             # T89


# T85: tool calls win when a response carries both.
def test_tool_calls_take_precedence_over_accompanying_text(run_cli, api):
    def responder(body, index):
        if any(m.get("role") == "tool" for m in body["messages"]):
            return 200, completion(FINAL)
        return 200, tool_call_completion(LOOKUP_Q1, content="Let me look that up.")
    mock = api(responder)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == {"answer": FINAL}
    assert len(r.rows[0]["result"]["tool_calls"]) == 1


# "5. If `max_iterations` is reached first, output `null` and use
#     `finish_reason: \"max_iterations\"`."
def test_max_iterations_stops_the_loop(run_cli, api):
    mock = always_tool(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, max_iterations=3), ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert mock.call_count == 3
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 3


# T88: `max_iterations` caps API requests, not tool rounds.
def test_max_iterations_of_one_sends_exactly_one_request(run_cli, api):
    mock = always_tool(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, max_iterations=1), ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 1
    assert r.rows[0]["meta"]["finish_reason"] == "max_iterations"


# ---------------------------------------------------------------------------
# "For chat mode, tool calls use the normal OpenAI shape"
# "parse `function.arguments` as JSON before invoking the handler"
# ---------------------------------------------------------------------------

def test_arguments_are_parsed_from_the_json_string(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    recorded = r.rows[0]["result"]["tool_calls"][0]
    assert recorded["args"] == {"key": "revenue_q1"}           # parsed, not a string


def test_arguments_string_with_escapes_is_parsed(run_cli, api):
    calls = [{"name": "calculate", "arguments": '{"expression": "2 + \\"x\\""}'}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["tool_calls"][0]["args"] == {"expression": '2 + "x"'}


# "if one model response contains multiple tool calls, execute and record all
#  of them for that iteration"
def test_multiple_tool_calls_in_one_response_all_execute(run_cli, api):
    mock = two_step(api, LOOKUP_BOTH)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    recorded = r.rows[0]["result"]["tool_calls"]
    assert len(recorded) == 2
    assert [c["iteration"] for c in recorded] == [1, 1]
    assert [c["args"]["key"] for c in recorded] == ["revenue_q1", "revenue_q2"]


def test_multiple_tool_calls_append_one_tool_message_each(run_cli, api):
    mock = two_step(api, LOOKUP_BOTH)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    roles = [m["role"] for m in mock.bodies[1]["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "tool"]


def test_multiple_tool_calls_count_as_one_iteration(run_cli, api):
    mock = two_step(api, LOOKUP_BOTH)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["iterations"] == 2


# T76: unknown tool names are reported, not fatal.
def test_unknown_tool_name_returns_an_error_result(run_cli, api):
    calls = [{"name": "nope", "arguments": {"key": "revenue_q1"}}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    recorded = r.rows[0]["result"]["tool_calls"][0]
    assert recorded["tool"] == "nope"
    assert recorded["result"].startswith("ERROR:")


def test_unparsable_arguments_do_not_kill_the_row(run_cli, api):
    calls = [{"name": "lookup", "arguments": "{not json"}]
    mock = two_step(api, calls)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == {"answer": FINAL}
    assert r.rows[0]["result"]["tool_calls"][0]["args"] == {}   # T76


# "each API request inside the loop counts separately toward request totals"
def test_every_loop_request_counts_in_the_summary(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.summary["total_api_calls"] == 2
    assert mock.call_count == 2


def test_loop_requests_count_per_task_in_multi_task_summaries(run_multi, api):
    mock = two_step(api, LOOKUP_Q1)
    task = copy.deepcopy(agentic_config(mock.url)["task"])
    task.pop("api_url")
    task.pop("model")
    task.pop("rpm")
    task.pop("name")
    cfg = make_multi_config(mock.url, {"data_lookup": task})
    r = run_multi(cfg, {"data_lookup": ROWS})
    assert r.code == 0, r.stderr
    assert r.summary["tasks"]["data_lookup"]["total_api_calls"] == 2


# "a single agentic run may span many API requests, but other inputs must
#  still be able to make progress concurrently"
# "do not fully serialize short batches; for example, if three input rows are
#  all pending and each needs a tool call followed by a final answer, requests
#  from different rows should still be able to overlap in flight"
def test_three_agentic_rows_overlap_in_flight(run_cli, api):
    rows = [{"question": "q%d" % i, "answer": "2730000"} for i in range(3)]
    mock = two_step(api, LOOKUP_Q1, delay=0.35)
    r = run_cli(agentic_config(mock.url), rows)
    assert r.code == 0, r.stderr
    assert mock.call_count == 6
    assert mock.max_inflight >= 3


def test_short_agentic_batch_is_not_fully_serialized(run_cli, api):
    rows = [{"question": "q%d" % i, "answer": "2730000"} for i in range(3)]
    mock = two_step(api, LOOKUP_Q1, delay=0.3)
    r = run_cli(agentic_config(mock.url), rows)
    assert r.code == 0, r.stderr
    elapsed = r.summary["elapsed_seconds"]
    assert elapsed < 6 * 0.3          # serialised would need ~1.8s


# ---------------------------------------------------------------------------
# Agentic Output
# "result.iterations is the number of API requests in the loop"
# ---------------------------------------------------------------------------

def test_iterations_counts_api_requests(run_cli, api):
    mock = two_step(api, LOOKUP_BOTH)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["iterations"] == mock.call_count == 2


# "result.tool_calls records every tool call in execution order"
# "each recorded tool call stores `iteration`, `tool`, parsed `args`, and the
#  handler `result`"
def test_recorded_tool_call_fields(run_cli, api):
    mock = two_step(api, LOOKUP_BOTH)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
         "result": "1250000"},
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"},
         "result": "1480000"},
    ]


def test_tool_calls_are_in_execution_order_across_iterations(run_cli, api):
    order = ["revenue_q1", "revenue_q2", "employees"]

    def responder(body, index):
        rounds = sum(1 for m in body["messages"] if m.get("role") == "tool")
        if rounds >= len(order):
            return 200, completion(FINAL)
        return 200, tool_call_completion(
            [{"name": "lookup", "arguments": {"key": order[rounds]}}])
    mock = api(responder)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    recorded = r.rows[0]["result"]["tool_calls"]
    assert [c["args"]["key"] for c in recorded] == order
    assert [c["iteration"] for c in recorded] == [1, 2, 3]


# "meta.total_* values are aggregated across all iterations"
def test_meta_totals_are_aggregated(run_cli, api):
    def responder(body, index):
        if any(m.get("role") == "tool" for m in body["messages"]):
            return 200, completion(FINAL, prompt_tokens=350, completion_tokens=40)
        return 200, tool_call_completion(LOOKUP_Q1, prompt_tokens=200,
                                         completion_tokens=30)
    mock = api(responder)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    meta = r.rows[0]["meta"]
    assert meta["total_prompt_tokens"] == 550
    assert meta["total_completion_tokens"] == 70
    assert meta["total_tokens"] == 620


# "meta.latency_ms is total wall-clock time for the loop"
def test_meta_latency_covers_the_whole_loop(run_cli, api):
    mock = two_step(api, LOOKUP_Q1, delay=0.2)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    meta = r.rows[0]["meta"]
    detail = meta["iterations_detail"]
    assert meta["latency_ms"] >= 400
    # Each per-iteration value rounds independently, so allow 1 ms of slack each.
    assert meta["latency_ms"] >= sum(d["latency_ms"] for d in detail) - len(detail)


# "meta.iterations_detail records per-iteration token usage, latency, and
#  finish reason"
def test_iterations_detail_one_entry_per_request(run_cli, api):
    def responder(body, index):
        if any(m.get("role") == "tool" for m in body["messages"]):
            return 200, completion(FINAL, prompt_tokens=300, completion_tokens=50)
        return 200, tool_call_completion(LOOKUP_Q1, prompt_tokens=200,
                                         completion_tokens=30)
    mock = api(responder)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    detail = r.rows[0]["meta"]["iterations_detail"]
    assert len(detail) == 2
    assert detail[0]["prompt_tokens"] == 200
    assert detail[0]["completion_tokens"] == 30
    assert detail[0]["total_tokens"] == 230
    assert detail[0]["finish_reason"] == "tool_calls"
    assert detail[1]["finish_reason"] == "stop"
    assert isinstance(detail[0]["latency_ms"], int)


def test_iterations_detail_entry_keys(run_cli, api):
    """The spec's entries carry exactly these five keys (T83)."""
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    for entry in r.rows[0]["meta"]["iterations_detail"]:
        assert set(entry) == {"prompt_tokens", "completion_tokens",
                              "total_tokens", "latency_ms", "finish_reason"}


def test_agentic_meta_keys(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert set(r.rows[0]["meta"]) == {
        "total_prompt_tokens", "total_completion_tokens", "total_tokens",
        "latency_ms", "finish_reason", "iterations_detail"}


# "meta.finish_reason is \"stop\" for a final text response"
def test_finish_reason_stop_for_final_text(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["meta"]["finish_reason"] == "stop"


# "and \"max_iterations\" when the iteration limit is hit"
def test_finish_reason_max_iterations(run_cli, api):
    mock = always_tool(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, max_iterations=2), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["meta"]["finish_reason"] == "max_iterations"
    assert len(r.rows[0]["meta"]["iterations_detail"]) == 2


# "evaluation runs against the final text output only"
def test_evaluation_scores_the_final_text(run_cli, api):
    mock = two_step(api, LOOKUP_BOTH, final="Total: 2730000")
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["extracted_answer"] == "2730000"
    assert r.rows[0]["result"]["passed"] is True


def test_tool_results_are_not_evaluated(run_cli, api):
    """The tool returned 1250000; only the final text decides the verdict."""
    mock = two_step(api, LOOKUP_Q1, final="I could not work it out.")
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is False


def test_spec_example_row_shape(run_cli, api):
    """The full per-row output object from the spec's Agentic Output block."""
    def responder(body, index):
        if any(m.get("role") == "tool" for m in body["messages"]):
            return 200, completion(FINAL)
        return 200, tool_call_completion(LOOKUP_BOTH)
    mock = api(responder)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["input"] == ROWS[0]
    assert row["output"] == {"answer": FINAL}
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "2730000"
    assert row["result"]["attempts"] == 1
    assert row["result"]["iterations"] == 2
    assert len(row["result"]["tool_calls"]) == 2
    assert set(row["result"]) == {"passed", "extracted_answer", "attempts",
                                  "iterations", "tool_calls"}


# "if max_iterations is hit, evaluation fails because output is null"
def test_max_iterations_row_fails_evaluation(run_cli, api):
    mock = always_tool(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, max_iterations=2), ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] is None
    assert r.summary["failed"] == 1
    assert r.summary["passed"] == 0


# T80: a failed evaluation does not start a second loop.
def test_single_solution_agentic_attempts_is_always_one(run_cli, api):
    mock = two_step(api, LOOKUP_Q1, final="nope")
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["attempts"] == 1
    assert mock.call_count == 2


# "when evaluation is omitted for a single-solution agentic row, keep the part
#  1 rule: result.passed is null, ..."
def test_no_evaluation_leaves_passed_null(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, evaluation=None), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is None
    assert r.rows[0]["output"] == {"answer": FINAL}


# "... except when max_iterations was reached, where it is false"
def test_no_evaluation_but_max_iterations_is_false(run_cli, api):
    mock = always_tool(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, evaluation=None, max_iterations=2), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is False
    assert r.rows[0]["output"] is None


# ---------------------------------------------------------------------------
# Agentic with ICL / num_solutions — the checkpoint 3 list format
# "agentic also works with ICL and num_solutions; each solution is an
#  independent loop"
# ---------------------------------------------------------------------------

ICL = {
    "setups": [
        {"name": "chain_of_thought",
         "examples": [{"input": {"question": "What is 2+2?"}, "output": "4"}]},
        {"name": "direct",
         "examples": [{"input": {"question": "What is 2+2?"}, "output": "#### 4"}]},
    ]
}


def test_num_solutions_runs_one_loop_per_solution(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, num_solutions=2), ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 4                  # two loops of two requests
    assert len(r.rows[0]["output"]) == 2


# "when ICL is configured or num_solutions > 1, keep the checkpoint 3 list
#  output format; each emitted output item represents one completed agentic
#  loop"
def test_list_format_output_items(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, num_solutions=2), ROWS)
    assert r.code == 0, r.stderr
    outputs = r.rows[0]["output"]
    assert isinstance(outputs, list)
    for item in outputs:
        assert item["answer"] == FINAL
        assert item["icl_setup"] is None


def test_icl_alone_switches_to_the_list_format(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    cfg = agentic_config(mock.url)
    cfg["task"]["icl"] = copy.deepcopy(ICL)
    r = run_cli(cfg, ROWS)
    assert r.code == 0, r.stderr
    assert isinstance(r.rows[0]["output"], list)
    assert isinstance(r.rows[0]["meta"], list)
    assert r.rows[0]["output"][0]["icl_setup"] == "chain_of_thought"


def test_icl_examples_are_in_the_initial_conversation(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    cfg = agentic_config(mock.url)
    cfg["task"]["icl"] = copy.deepcopy(ICL)
    r = run_cli(cfg, ROWS)
    assert r.code == 0, r.stderr
    roles = [m["role"] for m in mock.bodies[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


# "in that list format, result.attempts is the number of loops started for the
#  row, not the number of API requests across those loops"
def test_list_format_attempts_counts_loops(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, num_solutions=3), ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 6
    assert r.rows[0]["result"]["attempts"] == 3


def test_list_format_result_keys(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, num_solutions=2), ROWS)
    assert r.code == 0, r.stderr
    assert set(r.rows[0]["result"]) == {"passed", "failed", "attempts"}   # T78


# "in that list format, per-loop agentic metadata lives in each meta entry:
#  keep checkpoint 3's icl_setup / evaluation_passed fields and also record
#  that loop's aggregated total_prompt_tokens, total_completion_tokens,
#  total_tokens, latency_ms, finish_reason, and iterations_detail"
def test_list_format_meta_entry_fields(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, num_solutions=2), ROWS)
    assert r.code == 0, r.stderr
    metas = r.rows[0]["meta"]
    assert len(metas) == 2
    for entry in metas:
        assert set(entry) == {"icl_setup", "evaluation_passed",
                              "total_prompt_tokens", "total_completion_tokens",
                              "total_tokens", "latency_ms", "finish_reason",
                              "iterations_detail"}
        assert entry["finish_reason"] == "stop"
        assert len(entry["iterations_detail"]) == 2
        assert entry["evaluation_passed"] is True


def test_list_format_meta_totals_are_per_loop(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, num_solutions=2), ROWS)
    assert r.code == 0, r.stderr
    for entry in r.rows[0]["meta"]:
        assert entry["total_prompt_tokens"] == 60          # 2 requests x 30
        assert entry["total_completion_tokens"] == 20


def test_list_format_records_icl_setup_per_loop(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    cfg = agentic_config(mock.url, num_solutions=2)
    cfg["task"]["icl"] = copy.deepcopy(ICL)
    cfg["task"]["icl"]["strategy"] = "round_robin"
    r = run_cli(cfg, ROWS)
    assert r.code == 0, r.stderr
    names = [entry["icl_setup"] for entry in r.rows[0]["meta"]]
    assert names == ["chain_of_thought", "direct"]           # T79


# "when evaluation is omitted in the checkpoint 3 list format, keep the
#  checkpoint 3 rules: result.passed is the number of emitted outputs,
#  result.failed is the number of loops that produced no output, and each
#  metadata entry sets evaluation_passed to null"
def test_list_format_without_evaluation_counts_outputs(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, num_solutions=2, evaluation=None), ROWS)
    assert r.code == 0, r.stderr
    result = r.rows[0]["result"]
    assert result == {"passed": 2, "failed": 0, "attempts": 2}
    assert all(e["evaluation_passed"] is None for e in r.rows[0]["meta"])


def test_list_format_without_evaluation_counts_empty_loops_as_failed(run_cli, api):
    mock = always_tool(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url, num_solutions=2, evaluation=None,
                               max_iterations=2), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == []
    assert r.rows[0]["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert all(e["finish_reason"] == "max_iterations" for e in r.rows[0]["meta"])


def test_list_format_with_evaluation_counts_passes(run_cli, api):
    """First loop answers wrong, second answers right."""
    state = {"loops": 0}

    def responder(body, index):
        if any(m.get("role") == "tool" for m in body["messages"]):
            state["loops"] += 1
            text = "Total: 2730000" if state["loops"] > 1 else "Total: 11"
            return 200, completion(text)
        return 200, tool_call_completion(LOOKUP_Q1)
    mock = api(responder)
    r = run_cli(agentic_config(mock.url, num_solutions=2), ROWS)
    assert r.code == 0, r.stderr
    result = r.rows[0]["result"]
    assert result["attempts"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert len(r.rows[0]["output"]) == 2      # both loops emitted an output


# "Agentic list-format run: if num_solutions: 2 and both loops produce a final
#  answer on their first API request ... result.passed is 2, result.failed is
#  0, and result.attempts is 2 ... meta is a list with two entries"
def test_spec_example_agentic_list_format_run(run_cli, api):
    mock = api(lambda body, i: (200, completion("Total: 2730000")))
    r = run_cli(agentic_config(mock.url, num_solutions=2), ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert isinstance(row["meta"], list) and len(row["meta"]) == 2
    assert all(len(e["iterations_detail"]) == 1 for e in row["meta"])


# ---------------------------------------------------------------------------
# Completions Mode
# "When api_type is \"completions\", send requests to {api_url}/v1/completions
#  with a rendered prompt string instead of a messages array."
# ---------------------------------------------------------------------------

def completions_config(url, *, template="chatml", **over):
    cfg = make_config(url, **over)
    cfg["task"]["api_type"] = "completions"
    cfg["task"]["chat_template"] = template
    return cfg


MATH_ROWS = [{"question": "What is 2 + 3?", "answer": "5"}]
PASS = "2 + 3 = 5\n#### 5"
MATH_SYSTEM = "Solve the math problem. Final answer after ####."


@pytest.fixture
def text_api(api):
    return api(lambda body, i: (200, text_completion(PASS)))


def test_completions_requests_hit_the_completions_endpoint(run_cli, text_api):
    r = run_cli(completions_config(text_api.url), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert text_api.requests[0]["path"] == "/v1/completions"


def test_chat_mode_still_hits_the_chat_endpoint(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert echo_api.requests[0]["path"] == "/v1/chat/completions"


def test_completions_body_has_prompt_not_messages(run_cli, text_api):
    r = run_cli(completions_config(text_api.url), MATH_ROWS)
    assert r.code == 0, r.stderr
    body = text_api.bodies[0]
    assert "messages" not in body
    assert isinstance(body["prompt"], str)


# "completions requests send prompt, temperature, max_tokens, and model"
def test_completions_body_fields(run_cli, text_api):
    r = run_cli(completions_config(text_api.url), MATH_ROWS)
    assert r.code == 0, r.stderr
    body = text_api.bodies[0]
    assert set(body) == {"prompt", "temperature", "max_tokens", "model"}
    assert body["model"] == "gpt-4"
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 256


# "completions responses return choices[].text, not choices[].message"
def test_output_is_read_from_choices_text(run_cli, text_api):
    r = run_cli(completions_config(text_api.url), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == {"solution": PASS}
    assert r.rows[0]["result"]["extracted_answer"] == "5"


def test_completions_usage_and_finish_reason_are_recorded(run_cli, api):
    mock = api(lambda body, i: (200, text_completion(
        PASS, prompt_tokens=200, completion_tokens=50, finish_reason="length")))
    r = run_cli(completions_config(mock.url), MATH_ROWS)
    assert r.code == 0, r.stderr
    meta = r.rows[0]["meta"]
    assert meta["prompt_tokens"] == 200
    assert meta["completion_tokens"] == 50
    assert meta["total_tokens"] == 250
    assert meta["finish_reason"] == "length"


def test_chat_shaped_reply_to_a_completions_request_is_a_failure(run_cli, api):
    """No `text` key: the row fails rather than silently emitting nothing."""
    mock = api(lambda body, i: (200, completion(PASS)))
    r = run_cli(completions_config(mock.url), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] is None


# ---------------------------------------------------------------------------
# Config and CLI plumbing
# "defaults: api_type: \"completions\" / chat_template: \"llama3\""
# ---------------------------------------------------------------------------

def test_api_type_and_template_in_defaults(run_multi, api):
    mock = api(lambda body, i: (200, text_completion(PASS)))
    cfg = make_multi_config(mock.url, {
        "gsm8k": {
            "prompt": {"system": MATH_SYSTEM, "user": "{question}"},
            "generation": {"scheme": "greedy"},
            "output_field": "solution",
        }},
        defaults={"api_type": "completions", "chat_template": "llama3"})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert r.code == 0, r.stderr
    assert mock.requests[0]["path"] == "/v1/completions"
    assert mock.bodies[0]["prompt"].startswith("<|begin_of_text|>")


# "Per-task override: tasks: gsm8k: api_type: \"completions\" /
#  chat_template: \"chatml\""
def test_per_task_override_beats_defaults(run_multi, api):
    mock = api(lambda body, i: (200, text_completion(PASS)))
    base = {"prompt": {"system": MATH_SYSTEM, "user": "{question}"},
            "generation": {"scheme": "greedy"}, "output_field": "solution"}
    tasks = {
        "gsm8k": dict(base, api_type="completions", chat_template="chatml"),
        "mmlu": dict(base),
    }
    cfg = make_multi_config(mock.url, tasks, defaults={"chat_template": "llama3"})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS, "mmlu": MATH_ROWS})
    assert r.code == 0, r.stderr
    paths = {req["path"] for req in mock.requests}
    assert paths == {"/v1/completions", "/v1/chat/completions"}
    prompts = [b["prompt"] for b in mock.bodies if "prompt" in b]
    assert prompts and all(p.startswith("<|im_start|>") for p in prompts)


# "CLI flags: --api-type <chat|completions> / --chat-template
#  <chatml|llama3|mistral|zephyr>.  When provided, these CLI flags override the
#  config values."
def test_api_type_cli_flag(run_cli, api):
    mock = api(lambda body, i: (200, text_completion(PASS)))
    r = run_cli(make_config(mock.url), MATH_ROWS, args=["--api-type", "completions"])
    assert r.code == 0, r.stderr
    assert mock.requests[0]["path"] == "/v1/completions"


def test_chat_template_cli_flag_overrides_config(run_cli, api):
    mock = api(lambda body, i: (200, text_completion(PASS)))
    r = run_cli(completions_config(mock.url, template="chatml"), MATH_ROWS,
                args=["--chat-template", "mistral"])
    assert r.code == 0, r.stderr
    assert mock.bodies[0]["prompt"].startswith("[INST] ")


def test_api_type_cli_flag_can_force_chat(run_cli, echo_api):
    r = run_cli(completions_config(echo_api.url), MATH_ROWS,
                args=["--api-type", "chat"])
    assert r.code == 0, r.stderr
    assert echo_api.requests[0]["path"] == "/v1/chat/completions"


def test_invalid_api_type_is_a_config_error(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), MATH_ROWS, args=["--api-type", "grpc"])
    assert r.code == 1
    assert "api_type" in r.stderr


def test_invalid_chat_template_is_a_config_error(run_cli, echo_api):
    r = run_cli(completions_config(echo_api.url, template="alpaca"), MATH_ROWS)
    assert r.code == 1
    assert "chat_template" in r.stderr


# T81: chat_template is optional in completions mode.
def test_chat_template_defaults_to_chatml(run_cli, api):
    mock = api(lambda body, i: (200, text_completion(PASS)))
    cfg = completions_config(mock.url)
    cfg["task"].pop("chat_template")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.bodies[0]["prompt"].startswith("<|im_start|>system\n")


# ---------------------------------------------------------------------------
# Built-in templates
# "Built-in templates: chatml / llama3 / mistral / zephyr"
# ---------------------------------------------------------------------------

EXPECTED = {
    "chatml": ("<|im_start|>system\n%s<|im_end|>\n"
               "<|im_start|>user\n%s<|im_end|>\n"
               "<|im_start|>assistant\n"),
    "llama3": ("<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
               "%s<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
               "%s<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"),
    "mistral": "[INST] %s\n\n%s [/INST]",
    "zephyr": ("<|system|>\n%s</s>\n"
               "<|user|>\n%s</s>\n"
               "<|assistant|>\n"),
}


@pytest.mark.parametrize("template", ["chatml", "llama3", "mistral", "zephyr"])
def test_builtin_template_renders_the_spec_block(run_cli, api, template):
    mock = api(lambda body, i: (200, text_completion(PASS)))
    r = run_cli(completions_config(mock.url, template=template), MATH_ROWS)
    assert r.code == 0, r.stderr
    expected = EXPECTED[template] % (MATH_SYSTEM, MATH_ROWS[0]["question"])
    assert mock.bodies[0]["prompt"] == expected


# "built-in templates must handle multi-turn conversations by repeating the
#  correct role markers for every message"
MULTI_ICL = {
    "setups": [{
        "name": "cot",
        "examples": [
            {"input": {"question": "EX1"}, "output": "OUT1"},
            {"input": {"question": "EX2"}, "output": "OUT2"},
        ],
    }]
}

MULTI_EXPECTED = {
    "chatml": ("<|im_start|>system\nSYS<|im_end|>\n"
               "<|im_start|>user\nEX1<|im_end|>\n"
               "<|im_start|>assistant\nOUT1<|im_end|>\n"
               "<|im_start|>user\nEX2<|im_end|>\n"
               "<|im_start|>assistant\nOUT2<|im_end|>\n"
               "<|im_start|>user\nWhat is 2 + 3?<|im_end|>\n"
               "<|im_start|>assistant\n"),
    "llama3": ("<|begin_of_text|>"
               "<|start_header_id|>system<|end_header_id|>\n\nSYS<|eot_id|>"
               "<|start_header_id|>user<|end_header_id|>\n\nEX1<|eot_id|>"
               "<|start_header_id|>assistant<|end_header_id|>\n\nOUT1<|eot_id|>"
               "<|start_header_id|>user<|end_header_id|>\n\nEX2<|eot_id|>"
               "<|start_header_id|>assistant<|end_header_id|>\n\nOUT2<|eot_id|>"
               "<|start_header_id|>user<|end_header_id|>\n\nWhat is 2 + 3?<|eot_id|>"
               "<|start_header_id|>assistant<|end_header_id|>\n\n"),
    "mistral": ("[INST] SYS\n\nEX1 [/INST] OUT1</s>"
                "[INST] EX2 [/INST] OUT2</s>"
                "[INST] What is 2 + 3? [/INST]"),
    "zephyr": ("<|system|>\nSYS</s>\n"
               "<|user|>\nEX1</s>\n"
               "<|assistant|>\nOUT1</s>\n"
               "<|user|>\nEX2</s>\n"
               "<|assistant|>\nOUT2</s>\n"
               "<|user|>\nWhat is 2 + 3?</s>\n"
               "<|assistant|>\n"),
}


@pytest.mark.parametrize("template", ["chatml", "llama3", "mistral", "zephyr"])
def test_builtin_template_multi_turn(run_cli, api, template):
    mock = api(lambda body, i: (200, text_completion(PASS)))
    cfg = completions_config(mock.url, template=template)
    cfg["task"]["prompt"]["system"] = "SYS"
    cfg["task"]["icl"] = copy.deepcopy(MULTI_ICL)
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert mock.bodies[0]["prompt"] == MULTI_EXPECTED[template]


@pytest.mark.parametrize("template", ["chatml", "llama3", "zephyr"])
def test_template_without_a_system_prompt(run_cli, api, template):
    """A task with only `prompt.user` emits no system marker at all."""
    mock = api(lambda body, i: (200, text_completion(PASS)))
    cfg = completions_config(mock.url, template=template)
    cfg["task"]["prompt"].pop("system")
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert "system" not in mock.bodies[0]["prompt"]


# T82: judge calls follow the task's api_type.
def test_llm_judge_uses_the_configured_api_type(run_cli, api):
    def responder(body, index):
        prompt = body.get("prompt", "")
        text = "9" if "evaluator" in prompt else PASS
        return 200, text_completion(text)
    mock = api(responder)
    cfg = completions_config(mock.url, evaluation={
        "type": "llm_judge",
        "judge_prompt": {"system": "You are an evaluator.",
                         "user": "Rate 0-10: {__response__}"},
        "threshold": 7,
    })
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert all(req["path"] == "/v1/completions" for req in mock.requests)
    assert r.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Agentic behavior in completions mode
# "tool definitions are rendered into the prompt instead of being sent as a
#  native `tools` field"
# ---------------------------------------------------------------------------

def agentic_completions_config(url, *, template="chatml", **over):
    cfg = agentic_config(url, **over)
    cfg["task"]["api_type"] = "completions"
    cfg["task"]["chat_template"] = template
    return cfg


def test_completions_agentic_sends_no_native_tools_field(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_completions_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert "tools" not in mock.bodies[0]


def test_tool_definitions_appear_in_the_prompt(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_completions_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    prompt = mock.bodies[0]["prompt"]
    assert "lookup" in prompt
    assert "Look up a value in the database by key" in prompt
    assert "calculate" in prompt
    assert "<tool_call>" in prompt              # T72: the call protocol


# "parse tool calls from response text blocks of the form: <tool_call>{...}
#  </tool_call>"
def test_tool_call_blocks_are_parsed_from_text(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_completions_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    recorded = r.rows[0]["result"]["tool_calls"]
    assert recorded == [{"iteration": 1, "tool": "lookup",
                         "args": {"key": "revenue_q1"}, "result": "1250000"}]


def test_several_tool_call_blocks_in_one_response(run_cli, api):
    mock = two_step(api, LOOKUP_BOTH)
    r = run_cli(agentic_completions_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    recorded = r.rows[0]["result"]["tool_calls"]
    assert [c["args"]["key"] for c in recorded] == ["revenue_q1", "revenue_q2"]
    assert [c["iteration"] for c in recorded] == [1, 1]


def test_tool_call_block_with_surrounding_prose(run_cli, api):
    """T86: the block is found even when the model narrates around it."""
    block = "Let me check.\n" + tool_call_text(LOOKUP_Q1) + "\nOne moment."

    def responder(body, index):
        if "1250000" in body["prompt"]:
            return 200, text_completion(FINAL)
        return 200, text_completion(block)
    mock = api(responder)
    r = run_cli(agentic_completions_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert len(r.rows[0]["result"]["tool_calls"]) == 1
    assert r.rows[0]["output"] == {"answer": FINAL}


def test_text_without_a_tool_call_block_is_the_final_answer(run_cli, api):
    mock = api(lambda body, i: (200, text_completion(FINAL)))
    r = run_cli(agentic_completions_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == {"answer": FINAL}
    assert r.rows[0]["result"]["iterations"] == 1


# "execute those calls and feed the results back into the next prompt
#  iteration using the template's tool-role formatting"
def test_tool_results_are_fed_back_into_the_next_prompt(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_completions_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert len(mock.bodies) == 2
    second = mock.bodies[1]["prompt"]
    assert "1250000" in second
    assert "<|im_start|>tool\n1250000<|im_end|>\n" in second      # T71
    assert second.startswith("<|im_start|>system\n")


@pytest.mark.parametrize("template,marker", [
    ("chatml", "<|im_start|>tool\n1250000<|im_end|>"),
    ("llama3", "<|start_header_id|>tool<|end_header_id|>\n\n1250000<|eot_id|>"),
    ("zephyr", "<|tool|>\n1250000</s>"),
    ("mistral", "[TOOL_RESULTS] 1250000 [/TOOL_RESULTS]"),
])
def test_tool_role_formatting_per_template(run_cli, api, template, marker):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_completions_config(mock.url, template=template), ROWS)
    assert r.code == 0, r.stderr
    assert marker in mock.bodies[1]["prompt"]


def test_completions_agentic_assistant_turn_is_echoed_back(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_completions_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert "<tool_call>" in mock.bodies[1]["prompt"]


def test_completions_agentic_max_iterations(run_cli, api):
    mock = always_tool(api, LOOKUP_Q1)
    r = run_cli(agentic_completions_config(mock.url, max_iterations=2), ROWS)
    assert r.code == 0, r.stderr
    assert mock.call_count == 2
    assert r.rows[0]["output"] is None
    assert r.rows[0]["meta"]["finish_reason"] == "max_iterations"


def test_completions_agentic_row_shape(run_cli, api):
    mock = two_step(api, LOOKUP_BOTH, final="Total: 2730000")
    r = run_cli(agentic_completions_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["result"]["passed"] is True
    assert row["result"]["iterations"] == 2
    assert len(row["result"]["tool_calls"]) == 2
    assert row["meta"]["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# Examples
# "Simple lookup: if the model calls lookup(key=\"employees\") and the handler
#  returns \"142\" then a final response such as \"The company has 142
#  employees.\" is evaluated normally; result.iterations is 2 and
#  result.tool_calls contains the lookup"
# ---------------------------------------------------------------------------

def test_spec_example_simple_lookup(run_cli, api):
    mock = two_step(api, LOOKUP_EMPLOYEES, final="The company has 142 employees.")
    r = run_cli(agentic_config(mock.url), EMPLOYEE_ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] == {"answer": "The company has 142 employees."}
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "142"
    assert row["result"]["iterations"] == 2
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"},
         "result": "142"}]


# "Max-iteration failure: if the model keeps requesting tools and never
#  produces final text, stop at max_iterations, write output: null, set
#  meta.finish_reason to \"max_iterations\""
def test_spec_example_max_iteration_failure(run_cli, api):
    mock = always_tool(api, LOOKUP_EMPLOYEES)
    r = run_cli(agentic_config(mock.url, max_iterations=4), EMPLOYEE_ROWS)
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert mock.call_count == 4
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 4
    assert len(row["result"]["tool_calls"]) == 4


# "Completions-mode run: ... --api-type completions --chat-template llama3
#  ... This sends requests to /v1/completions and reads the model output from
#  choices[0].text."
def test_spec_example_completions_cli_run(run_cli, api):
    mock = api(lambda body, i: (200, text_completion(PASS)))
    r = run_cli(make_config(mock.url), MATH_ROWS,
                args=["--api-type", "completions", "--chat-template", "llama3"])
    assert r.code == 0, r.stderr
    assert mock.requests[0]["path"] == "/v1/completions"
    assert mock.bodies[0]["prompt"].startswith("<|begin_of_text|>")
    assert r.rows[0]["output"] == {"solution": PASS}


# ---------------------------------------------------------------------------
# Summary integration
# "each API request inside the loop counts separately toward request totals"
# ---------------------------------------------------------------------------

def test_summary_tokens_include_every_iteration(run_cli, api):
    mock = two_step(api, LOOKUP_Q1)
    r = run_cli(agentic_config(mock.url), ROWS)
    assert r.code == 0, r.stderr
    assert r.summary["total_prompt_tokens"] == 60
    assert r.summary["total_completion_tokens"] == 20
    assert r.summary["total_api_calls"] == 2


def test_summary_counts_agentic_rows(run_cli, api):
    rows = ROWS + [{"question": "other", "answer": "2730000"}]
    mock = two_step(api, LOOKUP_Q1, final="Total: 2730000")
    r = run_cli(agentic_config(mock.url), rows)
    assert r.code == 0, r.stderr
    assert r.summary["total"] == 2
    assert r.summary["passed"] == 2
    assert r.summary["failed"] == 0


def test_per_task_solution_counts_for_agentic_list_rows(run_multi, api):
    """Checkpoint 3's per-task `total_solutions` still counts emitted loops."""
    mock = two_step(api, LOOKUP_Q1, final="Total: 2730000")
    task = copy.deepcopy(agentic_config(mock.url, num_solutions=2)["task"])
    for key in ("api_url", "model", "rpm", "name"):
        task.pop(key, None)
    cfg = make_multi_config(mock.url, {"data_lookup": task})
    r = run_multi(cfg, {"data_lookup": ROWS})
    assert r.code == 0, r.stderr
    per_task = r.summary["tasks"]["data_lookup"]
    assert per_task["total_solutions"] == 2
    assert per_task["avg_solutions_per_input"] == 2.0
    assert per_task["total_api_calls"] == 4
