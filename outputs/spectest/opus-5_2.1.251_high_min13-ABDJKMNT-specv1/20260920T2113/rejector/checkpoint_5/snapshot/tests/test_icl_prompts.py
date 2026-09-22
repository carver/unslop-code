"""How ICL examples are turned into chat turns around the row's own message."""

from __future__ import annotations

from tests.conftest import icl_section, task_config
from tests.test_icl_config import SPEC_ICL

ROW = {"question": "What is 15 + 27?", "answer": "42"}


def greedy_icl(server, icl: dict, **overrides) -> dict:
    """A greedy single-attempt task carrying an `icl` section."""
    return task_config(api_url=server.url, icl=icl, **overrides)


def roles(server) -> list[str]:
    return [message["role"] for message in server.log.bodies[0]["messages"]]


def contents(server) -> list[str]:
    return [message["content"] for message in server.log.bodies[0]["messages"]]


# "ICL examples are inserted between the system message and the final user
#  message as alternating user and assistant turns"
def test_examples_become_alternating_turns_between_system_and_user(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(greedy_icl(server, SPEC_ICL), [ROW])
    assert run.returncode == 0, run.stderr
    assert roles(server) == ["system", "user", "assistant", "user", "assistant", "user"]


# "between the system message and the final user message"
def test_the_final_user_message_is_the_row_itself(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(greedy_icl(server, SPEC_ICL), [ROW])
    assert run.returncode == 0, run.stderr
    messages = server.log.bodies[0]["messages"]
    assert messages[0]["content"] == "Solve the math problem. Final answer after ####."
    assert messages[-1] == {"role": "user", "content": "What is 15 + 27?"}


# "each example's `input` is rendered with the task's `prompt.user` template"
def test_example_inputs_render_through_the_user_template(cli, static_api):
    server = static_api("B")
    config = greedy_icl(
        server,
        {"setups": [{"name": "mc", "examples": [
            {"input": {"question": "Capital?", "a": "Rome", "b": "Paris"}, "output": "B"},
        ]}]},
        prompt={"user": "{question}\n\nA) {a}\nB) {b}"},
    )
    run = cli.run(config, [{"question": "Largest?", "a": "Mars", "b": "Jupiter", "answer": "B"}])
    assert run.returncode == 0, run.stderr
    assert contents(server)[1] == "Capital?\n\nA) Rome\nB) Paris"
    assert contents(server)[-1] == "Largest?\n\nA) Mars\nB) Jupiter"


# "each example's `output` is inserted verbatim as the assistant message"
def test_example_outputs_are_verbatim_assistant_messages(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(greedy_icl(server, SPEC_ICL), [ROW])
    assert run.returncode == 0, run.stderr
    assistants = [
        message["content"] for message in server.log.bodies[0]["messages"]
        if message["role"] == "assistant"
    ]
    assert assistants == [
        "Let me think step by step.\n2 + 2 = 4\n#### 4",
        "Step by step:\nI start with 3 cats.\nI get 2 more.\n3 + 2 = 5\n#### 5",
    ]


# "`icl.k` defaults to all examples in the selected setup"
def test_all_examples_are_sent_when_k_is_omitted(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(greedy_icl(server, icl_section("cot")), [ROW])
    assert run.returncode == 0, run.stderr
    assert roles(server).count("assistant") == 2


# "if `k` is smaller than the number of examples in the setup, use the first `k`"
def test_k_truncates_to_the_first_examples(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(greedy_icl(server, icl_section("cot", k=1)), [ROW])
    assert run.returncode == 0, run.stderr
    assert roles(server) == ["system", "user", "assistant", "user"]
    assert contents(server)[2] == "cot demo\n#### 0"


# "ICL examples are inserted between the system message and the final user
#  message" - a task without a system prompt still starts with the examples
def test_examples_come_first_without_a_system_prompt(cli, static_api):
    server = static_api("#### 42")
    config = greedy_icl(server, icl_section("cot", k=1))
    config["task"]["prompt"] = {"user": "{question}"}
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert roles(server) == ["user", "assistant", "user"]
