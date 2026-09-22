"""ICL setup validation, example files, and the setup each attempt picks."""

import json

import pytest
import yaml

from config import load_config, overrides_from_flags
from errors import ConfigError
from icl import prepare_plan
from prompts import RenderedPrompt

SETUPS = [
    {
        "name": "chain_of_thought",
        "examples": [
            {"input": {"question": "What is 2+2?"}, "output": "2 + 2 = 4\n#### 4"},
            {"input": {"question": "3 cats plus 2?"}, "output": "3 + 2 = 5\n#### 5"},
        ],
    },
    {
        "name": "direct",
        "examples": [
            {"input": {"question": "What is 2+2?"}, "output": "#### 4"},
            {"input": {"question": "3 cats plus 2?"}, "output": "#### 5"},
        ],
    },
]

TASK = {
    "name": "gsm8k",
    "api_url": "http://localhost:8000",
    "model": "gpt-4",
    "rpm": 60,
    "prompt": {"system": "Solve it.", "user": "{question}"},
    "generation": {"scheme": "greedy"},
    "output_field": "solution",
}


def write_config(tmp_path, **changes):
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": {**TASK, **changes}}))
    return str(path)


def load_task(tmp_path, overrides=None, **changes):
    return load_config(write_config(tmp_path, **changes), overrides).tasks[0]


def write_examples(tmp_path, lines):
    directory = tmp_path / "icl"
    directory.mkdir(exist_ok=True)
    (directory / "detailed.jsonl").write_text("".join(f"{line}\n" for line in lines))
    return "icl/detailed.jsonl"


def test_inline_setups_keep_their_order_and_examples(tmp_path):
    icl = load_task(tmp_path, icl={"setups": SETUPS, "k": 2}).icl
    assert [setup.name for setup in icl.setups] == ["chain_of_thought", "direct"]
    assert icl.setups[0].examples[0].input == {"question": "What is 2+2?"}
    assert icl.setups[1].examples[1].output == "#### 5"
    assert (icl.k, icl.strategy) == (2, "fixed"), "the strategy defaults to fixed"


def test_setups_load_from_a_file_beside_the_config(tmp_path):
    lines = [json.dumps({"input": {"question": "What is 10 / 2?"}, "output": "#### 5"}), ""]
    setups = [{"name": "detailed", "file": write_examples(tmp_path, lines)}]
    icl = load_task(tmp_path, icl={"setups": setups, "k": 3}).icl
    assert len(icl.setups[0].examples) == 1, "blank lines are skipped"
    assert icl.setups[0].examples[0].output == "#### 5"


@pytest.mark.parametrize(
    "line, message",
    [
        ("not json", "invalid JSON"),
        ('{"input": {"question": "q"}}', "string 'output'"),
        ('{"output": "#### 5"}', "object 'input'"),
        ('{"input": "q", "output": "#### 5"}', "object 'input'"),
        ('["input", "output"]', "expected a JSON object"),
    ],
)
def test_a_malformed_example_line_is_a_config_error(tmp_path, line, message):
    setups = [{"name": "detailed", "file": write_examples(tmp_path, [line])}]
    with pytest.raises(ConfigError, match=message):
        load_task(tmp_path, icl={"setups": setups})


def test_a_missing_or_empty_example_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_task(tmp_path, icl={"setups": [{"name": "d", "file": "icl/nope.jsonl"}]})

    setups = [{"name": "detailed", "file": write_examples(tmp_path, [])}]
    with pytest.raises(ConfigError, match="contains no examples"):
        load_task(tmp_path, icl={"setups": setups})


def test_a_setup_needs_exactly_one_source(tmp_path):
    both = {"name": "d", "examples": SETUPS[0]["examples"], "file": "icl/detailed.jsonl"}
    with pytest.raises(ConfigError, match="exactly one of 'examples' or 'file'"):
        load_task(tmp_path, icl={"setups": [both]})

    with pytest.raises(ConfigError, match="exactly one of 'examples' or 'file'"):
        load_task(tmp_path, icl={"setups": [{"name": "d"}]})


def test_setups_must_be_named_and_non_empty(tmp_path):
    with pytest.raises(ConfigError, match="setups must not be empty"):
        load_task(tmp_path, icl={"setups": []})

    with pytest.raises(ConfigError, match=r"setups\[0\].name is required"):
        load_task(tmp_path, icl={"setups": [{"examples": SETUPS[0]["examples"]}]})

    with pytest.raises(ConfigError, match=r"setups\[0\].examples must not be empty"):
        load_task(tmp_path, icl={"setups": [{"name": "d", "examples": []}]})


def test_rejects_an_unknown_strategy_and_a_zero_k(tmp_path):
    with pytest.raises(ConfigError, match="strategy must be one of"):
        load_task(tmp_path, icl={"setups": SETUPS, "strategy": "shuffle"})
    with pytest.raises(ConfigError, match="k must be >= 1"):
        load_task(tmp_path, icl={"setups": SETUPS, "k": 0})


def test_num_solutions_defaults_to_one_and_must_be_positive(tmp_path):
    task = load_task(tmp_path)
    assert (task.num_solutions, task.list_output) == (1, False)
    assert load_task(tmp_path, num_solutions=4).list_output is True
    assert load_task(tmp_path, icl={"setups": SETUPS}).list_output is True

    with pytest.raises(ConfigError, match="num_solutions must be >= 1"):
        load_task(tmp_path, num_solutions=0)


def test_max_attempts_defaults_to_three_per_solution(tmp_path):
    generation = {"scheme": "rejection", "temperature": 0.7}
    evaluation = {"type": "exact_match", "answer_field": "answer"}
    task = load_task(tmp_path, generation=generation, evaluation=evaluation, num_solutions=5)
    assert task.generation.max_attempts == 15

    explicit = {**generation, "max_attempts": 8}
    task = load_task(tmp_path, generation=explicit, evaluation=evaluation, num_solutions=5)
    assert task.generation.max_attempts == 8


def test_cli_flags_override_the_icl_section(tmp_path):
    overrides = overrides_from_flags({"num_solutions": 3, "icl_strategy": "random", "icl_k": 1})
    task = load_task(tmp_path, overrides, icl={"setups": SETUPS, "k": 2})
    assert task.num_solutions == 3
    assert (task.icl.strategy, task.icl.k) == ("random", 1)


def test_icl_flags_do_not_give_icl_to_a_task_without_it(tmp_path):
    overrides = overrides_from_flags({"icl_strategy": "random"})
    assert load_task(tmp_path, overrides).icl is None


def test_k_takes_the_first_examples_of_each_setup(tmp_path):
    plan = prepare_plan(load_task(tmp_path, icl={"setups": SETUPS, "k": 1}).icl, "{question}")
    assert [setup.name for setup in plan.setups] == ["chain_of_thought", "direct"]
    assert plan.setups[0].turns == (("What is 2+2?", "2 + 2 = 4\n#### 4"),)

    plan = prepare_plan(load_task(tmp_path, icl={"setups": SETUPS, "k": 9}).icl, "{question}")
    assert len(plan.setups[0].turns) == 2, "a k above the example count shows them all"


def test_examples_render_through_the_task_user_template(tmp_path):
    plan = prepare_plan(load_task(tmp_path, icl={"setups": SETUPS}).icl, "Q: {question}")
    assert plan.setups[0].turns[0][0] == "Q: What is 2+2?"

    with pytest.raises(ConfigError, match="missing field 'context'"):
        prepare_plan(load_task(tmp_path, icl={"setups": SETUPS}).icl, "{context}: {question}")


def test_an_unconfigured_plan_chooses_nothing(tmp_path):
    plan = prepare_plan(None, "{question}")
    assert plan.setups == ()
    assert plan.choose(0) is None


@pytest.mark.parametrize(
    "strategy, expected",
    [
        ("fixed", ["chain_of_thought"] * 5),
        ("round_robin", ["chain_of_thought", "direct"] * 2 + ["chain_of_thought"]),
    ],
)
def test_strategies_walk_the_setups(tmp_path, strategy, expected):
    icl = load_task(tmp_path, icl={"setups": SETUPS, "strategy": strategy}).icl
    plan = prepare_plan(icl, "{question}")
    assert [plan.choose(index).name for index in range(5)] == expected


def test_random_stays_within_the_declared_setups(tmp_path):
    icl = load_task(tmp_path, icl={"setups": SETUPS, "strategy": "random"}).icl
    plan = prepare_plan(icl, "{question}")
    chosen = {plan.choose(index).name for index in range(50)}
    assert chosen <= {"chain_of_thought", "direct"}


def test_examples_sit_between_the_system_and_user_messages(tmp_path):
    plan = prepare_plan(load_task(tmp_path, icl={"setups": SETUPS, "k": 1}).icl, "{question}")
    prompt = RenderedPrompt(system="Solve it.", user="What is 7+1?", examples=plan.setups[0].turns)

    assert prompt.messages() == [
        {"role": "system", "content": "Solve it."},
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "2 + 2 = 4\n#### 4"},
        {"role": "user", "content": "What is 7+1?"},
    ]
