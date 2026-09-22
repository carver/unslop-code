"""The agentic loop: conversation growth, tool execution, and its stopping rules."""

from __future__ import annotations

from tests.conftest import AGENTIC_ROW, agentic_config, lookup_then_answer
from tests.fake_api import calls_ok, mentions, ok, tool_call

ANSWER = "The total revenue for Q1 and Q2 is $2,730,000."


def roles(body: dict) -> list[str]:
    return [message["role"] for message in body["messages"]]


# "Build the initial conversation from system prompt, optional ICL examples,
#  and final user prompt."
def test_first_request_is_the_system_and_user_prompt(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    first = server.log.bodies[0]["messages"]
    assert roles(server.log.bodies[0]) == ["system", "user"]
    assert first[0]["content"].startswith("You are a data analysis assistant.")
    assert first[1]["content"] == AGENTIC_ROW["question"]


# "In chat mode, include the task's tool definitions in the request body."
def test_chat_requests_carry_the_tool_definitions(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    tools = server.log.bodies[0]["tools"]
    assert [tool["function"]["name"] for tool in tools] == ["lookup", "calculate"]
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["description"] == "Look up a value in the database by key"
    assert tools[0]["function"]["parameters"]["required"] == ["key"]


# "If the response contains tool_calls, execute every tool call, append the
#  assistant tool-call message and the tool result messages to the conversation"
def test_second_request_appends_the_assistant_and_tool_messages(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    messages = server.log.bodies[1]["messages"]
    assert roles(server.log.bodies[1]) == ["system", "user", "assistant", "tool"]
    assert messages[2]["tool_calls"][0]["function"]["name"] == "lookup"
    assert messages[3]["content"] == "1250000"
    assert messages[3]["tool_call_id"] == messages[2]["tool_calls"][0]["id"]


# "parse function.arguments as JSON before invoking the handler"
def test_arguments_are_parsed_before_the_handler_runs(cli, api):
    server = api(lookup_then_answer("employees", "142", "The company has 142 employees."))
    run = cli.run(agentic_config(api_url=server.url), [{"question": "How many?",
                                                        "answer": "142"}])
    assert run.returncode == 0, run.stderr
    assert server.log.bodies[1]["messages"][-1]["content"] == "142"
    assert run.rows[0]["result"]["tool_calls"][0]["args"] == {"key": "employees"}


# "If the response contains final text and no tool calls, stop and use that
#  text as the output."
def test_final_text_ends_the_loop(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 2
    assert run.rows[0]["output"] == {"answer": ANSWER}


# "if the model calls lookup(key="employees") ... result.iterations is 2"
def test_one_tool_call_then_an_answer_is_two_iterations(cli, api):
    server = api(lookup_then_answer("employees", "142", "The company has 142 employees."))
    run = cli.run(agentic_config(api_url=server.url), [{"question": "How many?",
                                                        "answer": "142"}])
    assert run.returncode == 0, run.stderr
    result = run.rows[0]["result"]
    assert result["iterations"] == 2
    assert result["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]


# "if one model response contains multiple tool calls, execute and record all
#  of them for that iteration"
def test_multiple_tool_calls_in_one_response_all_run(cli, api):
    def responder(index, body):
        if mentions(body, "1480000"):
            return ok(ANSWER)
        return calls_ok(
            tool_call("lookup", {"key": "revenue_q1"}, "call_a"),
            tool_call("lookup", {"key": "revenue_q2"}, "call_b"),
        )

    server = api(responder)
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
         "result": "1250000"},
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"},
         "result": "1480000"},
    ]
    assert [m["content"] for m in server.log.bodies[1]["messages"] if m["role"] == "tool"] \
        == ["1250000", "1480000"]


# "append the assistant tool-call message and the tool result messages" - one
# tool message per call, each tied to its own call id.
def test_each_tool_call_gets_its_own_result_message(cli, api):
    def responder(index, body):
        if mentions(body, "1480000"):
            return ok(ANSWER)
        return calls_ok(
            tool_call("lookup", {"key": "revenue_q1"}, "call_a"),
            tool_call("lookup", {"key": "revenue_q2"}, "call_b"),
        )

    server = api(responder)
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    messages = server.log.bodies[1]["messages"]
    assert roles(server.log.bodies[1]) == ["system", "user", "assistant", "tool", "tool"]
    assert [m["tool_call_id"] for m in messages if m["role"] == "tool"] == \
        ["call_a", "call_b"]


# "the model keeps requesting tools and never produces final text / stop at
#  max_iterations / write output: null"
def test_max_iterations_stops_the_loop_with_a_null_output(cli, api):
    server = api(lambda index, body: calls_ok(tool_call("lookup", {"key": "employees"})))
    config = agentic_config(api_url=server.url, generation={"max_iterations": 3})
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 3
    assert run.rows[0]["output"] is None
    assert run.rows[0]["result"]["iterations"] == 3


# "each API request inside the loop counts separately toward request totals"
def test_every_loop_request_counts_in_the_summary(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW, AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert run.summary["total_api_calls"] == 4
    assert run.summary["total_prompt_tokens"] == 40


# "a single agentic run may span many API requests" - the row still reports one
# attempt in the single-solution format.
def test_a_multi_request_loop_is_still_one_attempt(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["attempts"] == 1


# A task without tools still runs: the first final text ends the loop.
def test_an_agentic_task_without_tools_sends_no_tools_field(cli, static_api):
    server = static_api(ANSWER)
    config = agentic_config(api_url=server.url)
    del config["task"]["tools"]
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert "tools" not in server.log.bodies[0]
    assert run.rows[0]["result"]["iterations"] == 1
