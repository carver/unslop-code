"""Agentic tasks in completions mode: rendered tools and `<tool_call>` text."""

from __future__ import annotations

from conftest import agentic_config
from fake_server import FakeAPIServer, conversation

ROW = {"question": "How many employees?", "answer": "142"}
ANSWER = "The company has 142 employees."
LOOKUP = [("lookup", {"key": "employees"})]


def _run(write_config, write_input, run_cli, *extra, template="chatml", responder=None, **kwargs):
    config_map = agentic_config("", api_type="completions", chat_template=template, **kwargs)
    with FakeAPIServer(responder or conversation([LOOKUP, ANSWER])) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input([ROW]), *extra)
        result.payloads = api.payloads
    return result


# Spec: "tool definitions are rendered into the prompt instead of being sent
# as a native `tools` field"
def test_tool_definitions_are_rendered_into_the_prompt(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli)

    prompt = result.payloads[0]["prompt"]
    assert "tools" not in result.payloads[0]
    assert "lookup" in prompt
    assert "Look up a value in the database by key" in prompt
    assert "<tool_call>" in prompt


# Spec: "parse tool calls from response text blocks of the form <tool_call>
# {"name": "lookup", "arguments": {"key": "revenue_q1"}} </tool_call>"
def test_tool_call_blocks_are_parsed_from_the_text(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli)

    call = result.rows[0]["result"]["tool_calls"][0]
    assert call == {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}


# Spec: "execute those calls and feed the results back into the next prompt
# iteration using the template's tool-role formatting"
def test_tool_results_are_fed_back_with_the_tool_role(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli)

    assert len(result.payloads) == 2
    assert "<|im_start|>tool\n142<|im_end|>" in result.payloads[1]["prompt"]


# Spec: "using the template's tool-role formatting" - each template has its
# own markers
def test_tool_results_use_the_configured_template(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, template="zephyr")

    assert "<|tool|>\n142</s>" in result.payloads[1]["prompt"]


# Spec: "execute those calls and feed the results back into the next prompt
# iteration" - the model's own tool-call turn stays in the conversation
def test_the_tool_call_turn_is_replayed_into_the_prompt(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli)

    assert result.payloads[1]["prompt"].count("</tool_call>") == 2


# Spec: "If the response contains final text and no tool calls, stop and use
# that text as the output."
def test_plain_text_ends_the_loop_in_completions_mode(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli)

    assert result.rows[0]["output"] == {"answer": ANSWER}
    assert result.rows[0]["result"]["iterations"] == 2
    assert result.rows[0]["meta"]["finish_reason"] == "stop"


# Spec: "if one model response contains multiple tool calls, execute and
# record all of them for that iteration"
def test_multiple_blocks_in_one_response_all_run(write_config, write_input, run_cli):
    both = [("lookup", {"key": "revenue_q1"}), ("lookup", {"key": "revenue_q2"})]
    result = _run(
        write_config, write_input, run_cli, responder=conversation([both, ANSWER])
    )

    calls = result.rows[0]["result"]["tool_calls"]
    assert [call["result"] for call in calls] == ["1250000", "1480000"]


# Spec: "If max_iterations is reached first, output null and use
# finish_reason: "max_iterations"."
def test_max_iterations_applies_in_completions_mode(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli, max_iterations=2, responder=conversation([LOOKUP])
    )

    assert result.rows[0]["output"] is None
    assert result.rows[0]["meta"]["finish_reason"] == "max_iterations"
    assert len(result.payloads) == 2


# Spec: "This sends requests to /v1/completions and reads the model output
# from choices[0].text." - the worked CLI example's flags
def test_cli_flags_switch_an_agentic_task_to_completions(write_config, write_input, run_cli):
    config_map = agentic_config("")
    with FakeAPIServer(conversation([LOOKUP, ANSWER])) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(
            write_config(config_map),
            write_input([ROW]),
            "--api-type", "completions",
            "--chat-template", "llama3",
        )
        paths, payloads = api.paths, api.payloads

    assert paths == ["/v1/completions", "/v1/completions"]
    assert payloads[1]["prompt"].count("<|start_header_id|>tool<|end_header_id|>") == 1
    assert result.rows[0]["output"] == {"answer": ANSWER}
