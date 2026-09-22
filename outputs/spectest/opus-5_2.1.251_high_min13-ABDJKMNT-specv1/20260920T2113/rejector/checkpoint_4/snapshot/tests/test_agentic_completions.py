"""Agentic tasks driven through `/v1/completions` and a chat template."""

from __future__ import annotations

from tests.conftest import AGENTIC_ROW, agentic_config, lookup_then_answer
from tests.fake_api import COMPLETIONS_PATH, text_ok, text_tool_call

ANSWER = "The total revenue for Q1 and Q2 is $2,730,000."


def completions_agentic(server, **overrides) -> dict:
    return agentic_config(api_url=server.url, api_type="completions",
                          chat_template="chatml", **overrides)


# "tool definitions are rendered into the prompt instead of being sent as a
#  native tools field"
def test_tool_definitions_are_rendered_into_the_prompt(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER, completions=True))
    run = cli.run(completions_agentic(server), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    prompt = server.log.prompts[0]
    assert "tools" not in server.log.bodies[0]
    assert [call.path for call in server.log.calls] == [COMPLETIONS_PATH] * 2
    assert "lookup" in prompt
    assert "Look up a value in the database by key" in prompt
    assert "calculate" in prompt
    assert "<tool_call>" in prompt


# "parse tool calls from response text blocks of the form <tool_call>{...}</tool_call>"
def test_a_tool_call_block_in_the_text_is_executed(cli, api):
    server = api(lookup_then_answer("employees", "142", "The company has 142 employees.",
                                    completions=True))
    run = cli.run(completions_agentic(server), [{"question": "How many?", "answer": "142"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]
    assert run.rows[0]["result"]["iterations"] == 2


# "execute those calls and feed the results back into the next prompt iteration
#  using the template's tool-role formatting"
def test_the_result_returns_in_the_next_prompt(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER, completions=True))
    run = cli.run(completions_agentic(server), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    second = server.log.prompts[1]
    assert "<|im_start|>tool\n1250000<|im_end|>\n" in second
    assert second.endswith("<|im_start|>assistant\n")
    assert "<|im_start|>assistant\n<tool_call>" in second


# Several blocks in one response are all executed, like chat-mode tool_calls.
def test_multiple_tool_call_blocks_all_run(cli, api):
    def respond(index, body):
        if "1480000" in body["prompt"]:
            return text_ok(ANSWER)
        return text_ok(text_tool_call("lookup", {"key": "revenue_q1"}) + "\n"
                       + text_tool_call("lookup", {"key": "revenue_q2"}))

    server = api(respond)
    run = cli.run(completions_agentic(server), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert [record["args"]["key"] for record in run.rows[0]["result"]["tool_calls"]] == \
        ["revenue_q1", "revenue_q2"]


# "If the response contains final text and no tool calls, stop"
def test_plain_text_ends_the_completions_loop(cli, api):
    server = api(lambda index, body: text_ok(ANSWER))
    run = cli.run(completions_agentic(server), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 1
    assert run.rows[0]["output"] == {"answer": ANSWER}
    assert run.rows[0]["meta"]["finish_reason"] == "stop"


# "If max_iterations is reached first, output null"
def test_completions_loop_stops_at_max_iterations(cli, api):
    server = api(lambda index, body: text_ok(text_tool_call("lookup", {"key": "employees"})))
    run = cli.run(completions_agentic(server, generation={"max_iterations": 3}),
                  [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 3
    assert run.rows[0]["output"] is None
    assert run.rows[0]["meta"]["finish_reason"] == "max_iterations"


# The example CLI invocation: flags pick the mode for an agentic task too.
def test_cli_flags_switch_an_agentic_task_to_completions(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER, completions=True))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW],
                  "--api-type", "completions", "--chat-template", "llama3")
    assert run.returncode == 0, run.stderr
    assert server.log.prompts[0].startswith("<|begin_of_text|>")
    assert run.rows[0]["output"] == {"answer": ANSWER}
