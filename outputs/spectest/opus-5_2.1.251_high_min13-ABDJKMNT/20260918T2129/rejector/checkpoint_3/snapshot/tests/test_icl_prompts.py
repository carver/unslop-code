"""ICL message layout and the setup chosen for each attempt."""

from __future__ import annotations

from fake_server import FakeAPIServer, always, assistants_of
from conftest import icl_config, icl_setup

ROW = {"question": "q", "answer": "5"}


def _run(write_config, write_input, run_cli, config_map, *extra, rows=None):
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input(rows or [ROW]), *extra)
        result.payloads = api.payloads
    return result


def _setups_used(payloads) -> list:
    """The setup behind each request, read back from its example answers."""
    return [assistants_of(payload)[0].split("-")[0] for payload in payloads]


def _sampling(config_map, num_solutions: int) -> dict:
    """Switch a config to sampling, which makes one attempt per solution."""
    config_map["task"]["generation"] = {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}
    config_map["task"]["num_solutions"] = num_solutions
    return config_map


# Spec: "ICL examples are inserted between the system message and the final
# user message as alternating user and assistant turns"
def test_examples_alternate_between_the_system_and_final_user_turns(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1", "A-2")])
    result = _run(write_config, write_input, run_cli, config_map)

    messages = result.payloads[0]["messages"]
    assert [message["role"] for message in messages] == [
        "system", "user", "assistant", "user", "assistant", "user",
    ]
    assert messages[0]["content"].startswith("Solve the math problem")
    assert messages[-1]["content"] == "q"


# Spec: "each example's input is rendered with the task's prompt.user template"
def test_example_inputs_are_rendered_with_the_user_template(write_config, write_input, run_cli):
    config_map = icl_config(
        "",
        [
            {
                "name": "A",
                "examples": [{"input": {"question": "2+2", "topic": "sums"}, "output": "#### 4"}],
            }
        ],
    )
    config_map["task"]["prompt"]["user"] = "Q: {question} [{topic}]"
    rows = [{"question": "q", "topic": "algebra", "answer": "5"}]
    result = _run(write_config, write_input, run_cli, config_map, rows=rows)

    messages = result.payloads[0]["messages"]
    assert messages[1]["content"] == "Q: 2+2 [sums]"
    assert messages[-1]["content"] == "Q: q [algebra]"


# Spec: "each example's output is inserted verbatim as the assistant message"
def test_example_outputs_are_inserted_verbatim(write_config, write_input, run_cli):
    output = "Step by step:\n3 + 2 = 5\n#### 5   "
    config_map = icl_config("", [icl_setup("A", output)])
    result = _run(write_config, write_input, run_cli, config_map)
    assert assistants_of(result.payloads[0]) == [output]


# Spec: "fixed: always use the first setup"
def test_fixed_strategy_always_uses_the_first_setup(write_config, write_input, run_cli):
    config_map = icl_config(
        "", [icl_setup("A", "A-1"), icl_setup("B", "B-1")], strategy="fixed"
    )
    result = _run(write_config, write_input, run_cli, _sampling(config_map, 3))
    assert _setups_used(result.payloads) == ["A", "A", "A"]


# Spec: "icl.strategy" is optional; the default keeps to the first setup
# (see AMBIGUITIES T35)
def test_strategy_defaults_to_fixed(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1"), icl_setup("B", "B-1")])
    result = _run(write_config, write_input, run_cli, _sampling(config_map, 3))
    assert _setups_used(result.payloads) == ["A", "A", "A"]


# Spec: "round_robin: cycle through setups in order across attempts" - the
# worked example: attempts 1-5 over [A, B, C] use A, B, C, A, B
def test_round_robin_cycles_through_setups_in_order(write_config, write_input, run_cli):
    setups = [icl_setup("A", "A-1"), icl_setup("B", "B-1"), icl_setup("C", "C-1")]
    config_map = icl_config("", setups, strategy="round_robin")
    result = _run(write_config, write_input, run_cli, _sampling(config_map, 5))
    assert _setups_used(result.payloads) == ["A", "B", "C", "A", "B"]


# Spec: "random: choose a setup independently for each attempt"
def test_random_strategy_varies_across_attempts(write_config, write_input, run_cli):
    config_map = icl_config(
        "", [icl_setup("A", "A-1"), icl_setup("B", "B-1")], strategy="random"
    )
    result = _run(write_config, write_input, run_cli, _sampling(config_map, 30))

    used = _setups_used(result.payloads)
    assert len(used) == 30
    assert set(used) == {"A", "B"}


# Spec: "for greedy with ICL and num_solutions > 1, selection ignores the
# above strategy and instead walks setups in declared order"
def test_greedy_walks_setups_in_declared_order(write_config, write_input, run_cli):
    setups = [icl_setup("A", "A-1"), icl_setup("B", "B-1"), icl_setup("C", "C-1")]
    config_map = icl_config("", setups, strategy="random")
    config_map["task"]["num_solutions"] = 3
    result = _run(write_config, write_input, run_cli, config_map)
    assert _setups_used(result.payloads) == ["A", "B", "C"]


# Spec: "at most once per setup" - greedy never revisits a setup
def test_greedy_visits_each_setup_at_most_once(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1"), icl_setup("B", "B-1")])
    config_map["task"]["num_solutions"] = 5
    result = _run(write_config, write_input, run_cli, config_map)
    assert _setups_used(result.payloads) == ["A", "B"]


# Spec: the strategy applies per row; a second row restarts the rotation
# (see AMBIGUITIES T36)
def test_round_robin_restarts_for_every_row(write_config, write_input, run_cli):
    setups = [icl_setup("A", "A-1"), icl_setup("B", "B-1")]
    config_map = icl_config("", setups, strategy="round_robin")
    rows = [{"question": "q0", "answer": "5"}, {"question": "q1", "answer": "5"}]
    result = _run(write_config, write_input, run_cli, _sampling(config_map, 2), rows=rows)

    by_row = {}
    for payload in result.payloads:
        question = payload["messages"][-1]["content"]
        by_row.setdefault(question, []).append(assistants_of(payload)[0].split("-")[0])
    assert by_row == {"q0": ["A", "B"], "q1": ["A", "B"]}
