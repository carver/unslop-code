"""ICL message layout and the setup each attempt is given."""

from __future__ import annotations

from conftest import base_task, icl_block, inline_setup, used_setup
from fake_api import FakeAPI, Reply, always, sequence

COT = inline_setup("chain_of_thought", "Let me think step by step.\n#### 4", "#### 5")
DIRECT = inline_setup("direct", "#### 4", "#### 5")
TERSE = inline_setup("terse", "4")


def icl_task(api_url: str, setups: list[dict], **icl_settings) -> dict:
    """A greedy task with ICL configured; `icl_settings` carries `k`/`strategy`."""
    task = base_task(api_url)
    task["icl"] = icl_block(setups, **icl_settings)
    return task


def rejection_icl_task(api_url: str, setups: list[dict], **icl_settings) -> dict:
    task = icl_task(api_url, setups, **icl_settings)
    task["generation"] = {"scheme": "rejection", "temperature": 0.7}
    return task


# Spec: "ICL examples are inserted between the system message and the final
# user message as alternating user and assistant turns"
# Context: ICL Configuration / Rules.
def test_examples_are_alternating_turns_between_system_and_user(
    write_config, write_input, run_cli
):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(icl_task(api.url, [COT]))
        data = write_input([{"question": "real question", "answer": "5"}])
        run_cli(config, data)
        messages = api.requests[0]["messages"]
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert messages[-1]["content"] == "real question"


# Spec: "each example's `input` is rendered with the task's `prompt.user`
# template"
# Context: ICL Configuration / Rules.
def test_example_inputs_are_rendered_with_the_user_template(
    write_config, write_input, run_cli
):
    task = icl_task("placeholder", [COT])
    task["prompt"]["user"] = "Q: {question}"
    with FakeAPI(responder=always("#### 5")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "real", "answer": "5"}])
        run_cli(config, data)
        messages = api.requests[0]["messages"]
    assert messages[1]["content"] == "Q: chain_of_thought q0"
    assert messages[3]["content"] == "Q: chain_of_thought q1"
    assert messages[-1]["content"] == "Q: real"


# Spec: "each example's `output` is inserted verbatim as the assistant message"
# Context: ICL Configuration / Rules.
def test_example_outputs_are_verbatim_assistant_messages(
    write_config, write_input, run_cli
):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(icl_task(api.url, [COT]))
        data = write_input([{"question": "real", "answer": "5"}])
        run_cli(config, data)
        messages = api.requests[0]["messages"]
    assert messages[2]["content"] == "Let me think step by step.\n#### 4"
    assert messages[4]["content"] == "#### 5"


# Spec: "if `k` is smaller than the number of examples in the setup, use the
# first `k`"
# Context: ICL Configuration / Rules.
def test_k_truncates_to_the_first_examples(write_config, write_input, run_cli):
    setup = inline_setup("direct", "a", "b", "c")
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(icl_task(api.url, [setup], k=2))
        data = write_input([{"question": "real", "answer": "5"}])
        run_cli(config, data)
        messages = api.requests[0]["messages"]
    assert [m["content"] for m in messages if m["role"] == "assistant"] == ["a", "b"]


# Spec: "`icl.k` defaults to all examples in the selected setup"
# Context: ICL Configuration / Rules.
def test_without_k_every_example_is_sent(write_config, write_input, run_cli):
    setup = inline_setup("direct", "a", "b", "c")
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(icl_task(api.url, [setup]))
        data = write_input([{"question": "real", "answer": "5"}])
        run_cli(config, data)
        messages = api.requests[0]["messages"]
    assert [m["content"] for m in messages if m["role"] == "assistant"] == ["a", "b", "c"]


# Spec: "`k` ... in the selected setup" — a larger `k` than the setup has
# examples uses the whole setup (see AMBIGUITIES T40).
# Context: ICL Configuration / Rules.
def test_k_larger_than_the_setup_uses_every_example(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(icl_task(api.url, [TERSE], k=9))
        data = write_input([{"question": "real", "answer": "5"}])
        run_cli(config, data)
        messages = api.requests[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]


# Spec: examples sit "between the system message and the final user message";
# a task without a system prompt starts with the demonstrations.
# Context: ICL Configuration / Rules.
def test_examples_come_first_without_a_system_prompt(write_config, write_input, run_cli):
    task = icl_task("placeholder", [TERSE])
    task["prompt"] = {"user": "{question}"}
    with FakeAPI(responder=always("#### 5")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "real", "answer": "5"}])
        run_cli(config, data)
        messages = api.requests[0]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]


# Spec: "`fixed`: always use the first setup"
# Context: Strategy behavior.
def test_fixed_always_uses_the_first_setup(write_config, write_input, run_cli):
    task = rejection_icl_task("placeholder", [COT, DIRECT, TERSE], strategy="fixed")
    task["num_solutions"] = 4
    with FakeAPI(responder=always("#### 0")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "real", "answer": "5"}])
        run_cli(config, data)
        used = [used_setup(body) for body in api.requests]
    assert set(used) == {"chain_of_thought"}


# Spec: "`round_robin`: cycle through setups in order across attempts" with
# "attempt 1 uses A ... attempt 4 uses A, attempt 5 uses B"
# Context: Strategy behavior / Examples.
def test_round_robin_cycles_across_attempts(write_config, write_input, run_cli):
    task = rejection_icl_task("placeholder", [COT, DIRECT, TERSE], strategy="round_robin")
    task["num_solutions"] = 3
    task["generation"]["max_attempts"] = 5
    with FakeAPI(responder=always("#### 0")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "real", "answer": "5"}])
        run_cli(config, data)
        used = [used_setup(body) for body in api.requests]
    assert used == ["chain_of_thought", "direct", "terse", "chain_of_thought", "direct"]


# Spec: "`random`: choose a setup independently for each attempt"
# Context: Strategy behavior; over many attempts both setups show up.
def test_random_varies_the_setup_across_attempts(write_config, write_input, run_cli):
    task = rejection_icl_task("placeholder", [COT, DIRECT], strategy="random")
    task["num_solutions"] = 24
    task["generation"]["max_attempts"] = 24
    with FakeAPI(responder=always("#### 0"), delay=0.0) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "real", "answer": "5"}])
        run_cli(config, data)
        used = [used_setup(body) for body in api.requests]
    assert len(used) == 24
    assert set(used) == {"chain_of_thought", "direct"}


# Spec: "for `greedy` with ICL and `num_solutions > 1`, selection ignores the
# above strategy and instead walks setups in declared order, at most once per
# setup"
# Context: Strategy behavior.
def test_greedy_walks_setups_in_declared_order(write_config, write_input, run_cli):
    task = icl_task("placeholder", [COT, DIRECT, TERSE], strategy="fixed")
    task["num_solutions"] = 3
    with FakeAPI(responder=always("#### 5")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "real", "answer": "5"}])
        run_cli(config, data)
        used = [used_setup(body) for body in api.requests]
    assert used == ["chain_of_thought", "direct", "terse"]


# Spec: "round_robin ... across attempts" — each input row runs its own attempt
# sequence (see AMBIGUITIES T34).
# Context: Strategy behavior.
def test_round_robin_restarts_for_every_row(write_config, write_input, run_cli):
    task = rejection_icl_task("placeholder", [COT, DIRECT], strategy="round_robin")
    task["num_solutions"] = 2
    task["generation"]["max_attempts"] = 2
    task["rate_limits"] = {"max_concurrent": 1}
    with FakeAPI(responder=sequence([Reply(content="#### 0")]), slots=1) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "a", "answer": "5"}, {"question": "b", "answer": "5"}])
        run_cli(config, data)
        used = [used_setup(body) for body in api.requests]
    assert used == ["chain_of_thought", "direct", "chain_of_thought", "direct"]


# Spec: "each example's `input` is rendered with the task's `prompt.user`
# template" — an example that cannot be rendered is a configuration error
# (see AMBIGUITIES T41).
# Context: ICL Configuration / Rules.
def test_example_missing_a_template_field_exits_1(write_config, write_input, run_cli):
    setup = {"name": "bad", "examples": [{"input": {"other": "x"}, "output": "#### 4"}]}
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(icl_task(api.url, [setup]))
        data = write_input([{"question": "real", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 0
    assert result.returncode == 1
    assert "question" in result.stderr
