"""ICL configuration, example files, rendered turns and setup selection."""

import json

import pytest
import yaml
from test_config import NO_OVERRIDES

from config import load_tasks
from errors import RejectorError
from icl import RenderedSetup, render_setups, select

SETUPS = [
    {
        "name": "chain_of_thought",
        "examples": [
            {"input": {"question": "What is 2+2?"}, "output": "Let me think step by step.\n2 + 2 = 4\n#### 4"},
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
    "prompt": {"system": "Solve it.", "user": "{question}"},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
}

FILE_EXAMPLES = [
    {"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\n#### 5"},
    {"input": {"question": "What is 1 + 1?"}, "output": "#### 2"},
]


def write_config(tmp_path, icl=None, **task):
    path = tmp_path / "task.yaml"
    document = {"task": {**TASK, **task}}
    if icl is not None:
        document["task"]["icl"] = icl
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return str(path)


def load(tmp_path, icl=None, overrides=None, **task):
    return load_tasks(write_config(tmp_path, icl, **task), {**NO_OVERRIDES, **(overrides or {})}).tasks[0]


def write_examples(tmp_path, *lines):
    directory = tmp_path / "icl"
    directory.mkdir(exist_ok=True)
    (directory / "examples.jsonl").write_text("".join(f"{line}\n" for line in lines))
    return {"name": "detailed", "file": "icl/examples.jsonl"}


def test_inline_setups_are_loaded_in_order(tmp_path):
    config = load(tmp_path, {"setups": SETUPS, "k": 2, "strategy": "round_robin"}).icl
    assert [setup.name for setup in config.setups] == ["chain_of_thought", "direct"]
    assert (config.k, config.strategy) == (2, "round_robin")


def test_absent_icl_section_leaves_the_task_single_solution(tmp_path):
    task = load(tmp_path)
    assert task.icl is None and task.multi_solution is False


def test_strategy_defaults_to_fixed_and_k_to_every_example(tmp_path):
    config = load(tmp_path, {"setups": SETUPS}).icl
    assert (config.strategy, config.k) == ("fixed", None)


def test_examples_become_alternating_user_and_assistant_turns(tmp_path):
    task = load(tmp_path, {"setups": SETUPS})
    messages = render_setups(task.icl, task.prompt.user)[0].messages
    assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0] == {"role": "user", "content": "What is 2+2?"}
    assert messages[1]["content"] == "Let me think step by step.\n2 + 2 = 4\n#### 4"


def test_k_keeps_the_first_examples_only(tmp_path):
    task = load(tmp_path, {"setups": SETUPS, "k": 1})
    setups = render_setups(task.icl, task.prompt.user)
    assert [len(setup.messages) for setup in setups] == [2, 2]
    assert setups[0].messages[0]["content"] == "What is 2+2?"


def test_k_above_the_example_count_uses_them_all(tmp_path):
    task = load(tmp_path, {"setups": SETUPS, "k": 9})
    assert len(render_setups(task.icl, task.prompt.user)[0].messages) == 4


def test_cli_flags_override_strategy_and_k(tmp_path):
    config = load(
        tmp_path,
        {"setups": SETUPS, "k": 2, "strategy": "fixed"},
        overrides={"icl_strategy": "random", "icl_k": 1},
    ).icl
    assert (config.strategy, config.k) == ("random", 1)


def test_file_backed_setups_are_read_relative_to_the_config(tmp_path):
    setup = write_examples(tmp_path, *(json.dumps(example) for example in FILE_EXAMPLES))
    config = load(tmp_path, {"setups": [setup], "k": 3}).icl
    assert config.setups[0].examples[0].input == {"question": "What is 10 / 2?"}
    assert config.setups[0].examples[1].output == "#### 2"


def test_blank_lines_in_an_example_file_are_skipped(tmp_path):
    setup = write_examples(tmp_path, json.dumps(FILE_EXAMPLES[0]), "", json.dumps(FILE_EXAMPLES[1]))
    assert len(load(tmp_path, {"setups": [setup]}).icl.setups[0].examples) == 2


@pytest.mark.parametrize(
    "line, message",
    [
        ("{not json}", "invalid JSON"),
        ('{"output": "#### 4"}', "'input' must be an object"),
        ('{"input": {"question": "q"}}', "'output' must be a string"),
        ('{"input": "q", "output": "#### 4"}', "'input' must be an object"),
        ('{"input": {"question": "q"}, "output": 4}', "'output' must be a string"),
    ],
)
def test_malformed_example_lines_are_reported(tmp_path, line, message):
    setup = write_examples(tmp_path, json.dumps(FILE_EXAMPLES[0]), line)
    with pytest.raises(RejectorError, match=message):
        load(tmp_path, {"setups": [setup]})


def test_a_missing_example_file_is_an_error(tmp_path):
    with pytest.raises(OSError):
        load(tmp_path, {"setups": [{"name": "detailed", "file": "icl/nowhere.jsonl"}]})


@pytest.mark.parametrize(
    "setups, message",
    [
        ([], "setups must be a non-empty list"),
        ([{"examples": SETUPS[0]["examples"]}], "name is required"),
        ([{"name": "both", "examples": [], "file": "x.jsonl"}], "exactly one of 'examples' or 'file'"),
        ([{"name": "neither"}], "exactly one of 'examples' or 'file'"),
        ([{"name": "empty", "examples": []}], "has no examples"),
    ],
)
def test_invalid_setups_are_rejected(tmp_path, setups, message):
    with pytest.raises(RejectorError, match=message):
        load(tmp_path, {"setups": setups})


def test_an_unknown_strategy_is_rejected(tmp_path):
    with pytest.raises(RejectorError, match="icl.strategy must be one of"):
        load(tmp_path, {"setups": SETUPS, "strategy": "shuffle"})


def test_k_must_be_positive(tmp_path):
    with pytest.raises(RejectorError, match="icl.k must be >= 1"):
        load(tmp_path, {"setups": SETUPS, "k": 0})


def test_an_example_missing_a_prompt_field_is_reported(tmp_path):
    task = load(tmp_path, {"setups": [{"name": "typo", "examples": [{"input": {"q": "2+2"}, "output": "4"}]}]})
    with pytest.raises(RejectorError, match="icl setup 'typo': example input is missing field 'question'"):
        render_setups(task.icl, task.prompt.user)


def rendered(*names):
    return tuple(RenderedSetup(name=name, messages=()) for name in names)


def test_fixed_always_picks_the_first_setup():
    setups = rendered("a", "b", "c")
    assert [select(setups, "fixed", attempt).name for attempt in range(4)] == ["a", "a", "a", "a"]


def test_round_robin_cycles_through_the_setups():
    setups = rendered("a", "b", "c")
    assert [select(setups, "round_robin", attempt).name for attempt in range(5)] == ["a", "b", "c", "a", "b"]


def test_random_picks_from_the_setups(monkeypatch):
    setups = rendered("a", "b")
    monkeypatch.setattr("icl.random.choice", lambda options: options[-1])
    assert select(setups, "random", attempt=0).name == "b"
