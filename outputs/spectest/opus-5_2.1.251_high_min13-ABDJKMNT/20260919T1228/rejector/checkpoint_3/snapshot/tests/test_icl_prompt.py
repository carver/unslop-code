"""Where ICL turns go in the request and how they are rendered."""

from __future__ import annotations

from conftest import make_config

ROW = [{"question": "What is 15 + 27?", "answer": "42"}]

SPEC_SETUP = {
    "name": "chain_of_thought",
    "examples": [
        {
            "input": {"question": "What is 2+2?"},
            "output": "Let me think step by step.\n2 + 2 = 4\n#### 4",
        },
        {
            "input": {"question": "If I have 3 cats and get 2 more, how many cats do I have?"},
            "output": "Step by step:\nI start with 3 cats.\nI get 2 more.\n3 + 2 = 5\n#### 5",
        },
    ],
}


# Spec: "ICL examples are inserted between the system message and the final
# user message as alternating user and assistant turns".
def test_examples_sit_between_system_and_the_final_user_turn(server, run_cli):
    config = make_config(server.url, icl={"setups": [SPEC_SETUP]})
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    roles = [message["role"] for message in server.payloads[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]


# Spec: "each example's `input` is rendered with the task's `prompt.user`
# template".
def test_example_input_uses_the_user_template(server, run_cli):
    config = make_config(
        server.url,
        prompt={"system": "Solve it.", "user": "Question: {question}"},
        icl={"setups": [SPEC_SETUP]},
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    messages = server.payloads[0]["messages"]
    assert messages[1]["content"] == "Question: What is 2+2?"
    assert messages[-1]["content"] == "Question: What is 15 + 27?"


# Spec: "each example's `output` is inserted verbatim as the assistant
# message".
def test_example_output_is_verbatim(server, run_cli):
    config = make_config(server.url, icl={"setups": [SPEC_SETUP]})
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert server.payloads[0]["messages"][2] == {
        "role": "assistant",
        "content": "Let me think step by step.\n2 + 2 = 4\n#### 4",
    }


# Spec: examples come "between the system message and the final user message"
# -- a task with no system prompt starts with the examples. (T)
def test_examples_come_first_without_a_system_prompt(server, run_cli):
    config = make_config(
        server.url, prompt={"user": "{question}"}, icl={"setups": [SPEC_SETUP]}
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    roles = [message["role"] for message in server.payloads[0]["messages"]]
    assert roles == ["user", "assistant", "user", "assistant", "user"]


# Spec: the system message is unchanged by ICL, and the row's own turn is last.
def test_system_and_row_turns_are_unchanged(server, run_cli):
    config = make_config(server.url, icl={"setups": [SPEC_SETUP]})
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    messages = server.payloads[0]["messages"]
    assert messages[0] == {
        "role": "system",
        "content": "Solve the math problem. Put your final answer after ####.",
    }
    assert messages[-1] == {"role": "user", "content": "What is 15 + 27?"}


# Spec: "Existing behavior from earlier parts is unchanged unless stated here"
# -- a task without an `icl` block sends the Part 1 messages.
def test_task_without_icl_sends_two_messages(server, run_cli):
    result = run_cli(make_config(server.url), ROW)
    assert result.exit_code == 0, result.stderr
    assert [message["role"] for message in server.payloads[0]["messages"]] == [
        "system",
        "user",
    ]
