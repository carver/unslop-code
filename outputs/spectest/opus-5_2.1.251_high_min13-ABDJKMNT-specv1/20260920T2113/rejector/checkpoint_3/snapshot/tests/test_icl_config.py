"""ICL configuration: setups, example files, `k`, strategy, and `num_solutions`."""

from __future__ import annotations

import pytest

from rejlib.config import load_config
from rejlib.errors import ConfigError
from tests.conftest import icl_section, icl_setup, multi_config, task_config

#: The spec's `icl` block, copied verbatim from the configuration example.
SPEC_ICL = {
    "setups": [
        {
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
        },
        {
            "name": "direct",
            "examples": [
                {"input": {"question": "What is 2+2?"}, "output": "#### 4"},
                {
                    "input": {"question": "If I have 3 cats and get 2 more, how many cats do I have?"},
                    "output": "#### 5",
                },
            ],
        },
    ],
    "k": 2,
    "strategy": "round_robin",
}

FILE_LINE = '{"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\\n#### 5"}'


def load(cli, config, name: str = "task.yaml", **overrides):
    return load_config(cli.write_config(config, name), overrides)


def only(cli, config, **overrides):
    """The single task of a Part 1 config, after overrides."""
    return load(cli, config, **overrides).only


# "Tasks may define named ICL setups" - the spec's example block
def test_named_setups_load_in_declared_order(cli):
    task = only(cli, task_config(icl=SPEC_ICL))
    assert [setup.name for setup in task.icl.setups] == ["chain_of_thought", "direct"]


# "examples: - input: {question: ...} / output: ..."
def test_inline_examples_keep_their_input_and_output(cli):
    setup = only(cli, task_config(icl=SPEC_ICL)).icl.setups[0]
    assert setup.examples[0].input == {"question": "What is 2+2?"}
    assert setup.examples[0].output == "Let me think step by step.\n2 + 2 = 4\n#### 4"
    assert len(setup.examples) == 2


# "k: 2" / "strategy: round_robin"
def test_k_and_strategy_come_from_the_icl_section(cli):
    icl = only(cli, task_config(icl=SPEC_ICL)).icl
    assert icl.k == 2
    assert icl.strategy == "round_robin"


# "Setups may also come from files" / "File format: {"input": ..., "output": ...}"
def test_file_backed_setup_reads_jsonl_examples(cli):
    cli.write_input(FILE_LINE + "\n", name="icl/gsm8k_detailed.jsonl")
    config = task_config(icl={
        "setups": [{"name": "detailed", "file": "icl/gsm8k_detailed.jsonl"}],
        "k": 3,
        "strategy": "fixed",
    })
    setup = only(cli, config).icl.setups[0]
    assert setup.name == "detailed"
    assert setup.examples[0].input == {"question": "What is 10 / 2?"}
    assert setup.examples[0].output == "10 divided by 2 is 5.\n#### 5"


# "file paths are relative to the config file directory"
def test_file_paths_resolve_against_the_config_directory(cli):
    cli.write_input(FILE_LINE + "\n", name="nested/icl/examples.jsonl")
    config = task_config(icl={"setups": [{"name": "detailed", "file": "icl/examples.jsonl"}]})
    task = load(cli, config, name="nested/task.yaml").only
    assert len(task.icl.setups[0].examples) == 1


# "file paths are relative to the config file directory" - not to the cwd
def test_file_missing_relative_to_the_config_directory_is_an_error(cli):
    cli.write_input(FILE_LINE + "\n", name="examples.jsonl")
    config = task_config(icl={"setups": [{"name": "detailed", "file": "examples.jsonl"}]})
    with pytest.raises(ConfigError):
        load(cli, config, name="nested/task.yaml")


# "each setup has a `name` and exactly one of `examples` or `file`"
def test_setup_without_a_name_is_an_error(cli):
    config = task_config(icl={"setups": [{"examples": [{"input": {"question": "q"}, "output": "a"}]}]})
    with pytest.raises(ConfigError, match="name"):
        load(cli, config)


# "exactly one of `examples` or `file`" - both given
def test_setup_with_both_examples_and_file_is_an_error(cli):
    cli.write_input(FILE_LINE + "\n", name="icl.jsonl")
    config = task_config(icl={"setups": [dict(icl_setup("both"), file="icl.jsonl")]})
    with pytest.raises(ConfigError, match="exactly one"):
        load(cli, config)


# "exactly one of `examples` or `file`" - neither given
def test_setup_with_neither_examples_nor_file_is_an_error(cli):
    with pytest.raises(ConfigError, match="exactly one"):
        load(cli, task_config(icl={"setups": [{"name": "empty"}]}))


# "malformed lines or missing keys must terminate the run with exit code 1" /
# "malformed line errors include `not valid JSON`"
def test_malformed_example_line_mentions_invalid_json(cli):
    cli.write_input(FILE_LINE + "\n{oops\n", name="icl.jsonl")
    config = task_config(icl={"setups": [{"name": "detailed", "file": "icl.jsonl"}]})
    with pytest.raises(ConfigError, match="not valid JSON"):
        load(cli, config)


# "each non-empty line has `{"input": <object>, "output": <string>}`"
@pytest.mark.parametrize("line", [
    '{"output": "just an answer"}',
    '{"input": {"question": "q"}}',
    '{"input": "not an object", "output": "a"}',
    '{"input": {"question": "q"}, "output": 5}',
    '["input", "output"]',
])
def test_example_lines_need_an_input_object_and_an_output_string(cli, line):
    cli.write_input(line + "\n", name="icl.jsonl")
    config = task_config(icl={"setups": [{"name": "detailed", "file": "icl.jsonl"}]})
    with pytest.raises(ConfigError):
        load(cli, config)


# "each non-empty line" - blank lines are skipped, like the input file
def test_blank_lines_in_an_example_file_are_skipped(cli):
    cli.write_input("\n" + FILE_LINE + "\n\n", name="icl.jsonl")
    config = task_config(icl={"setups": [{"name": "detailed", "file": "icl.jsonl"}]})
    assert len(only(cli, config).icl.setups[0].examples) == 1


# "must terminate the run with exit code 1 before any API requests are sent"
def test_malformed_example_file_exits_before_any_request(cli, static_api):
    server = static_api("#### 5")
    cli.write_input("{oops\n", name="icl.jsonl")
    config = task_config(
        api_url=server.url,
        icl={"setups": [{"name": "detailed", "file": "icl.jsonl"}]},
    )
    run = cli.run(config, [{"question": "What is 2 + 3?", "answer": "5"}])
    assert run.returncode == 1
    assert "not valid JSON" in run.stderr
    assert server.log.calls == []


# "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"
@pytest.mark.parametrize("strategy", ["fixed", "random", "round_robin"])
def test_every_documented_strategy_is_accepted(cli, strategy):
    task = only(cli, task_config(icl=icl_section("a", "b", strategy=strategy)))
    assert task.icl.strategy == strategy


# "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"
def test_unknown_strategy_is_an_error(cli):
    with pytest.raises(ConfigError, match="strategy"):
        load(cli, task_config(icl=icl_section("a", strategy="greedy_first")))


# T39: `icl.strategy` is optional and defaults to `fixed`
def test_strategy_defaults_to_fixed(cli):
    assert only(cli, task_config(icl=icl_section("a", "b"))).icl.strategy == "fixed"


# "`icl.k` defaults to all examples in the selected setup"
def test_k_defaults_to_all_examples_of_the_setup(cli):
    icl = only(cli, task_config(icl=icl_section("a"))).icl
    assert icl.k is None
    assert len(icl.examples(icl.setups[0])) == 2


# "if `k` is smaller than the number of examples in the setup, use the first `k`"
def test_k_smaller_than_the_setup_takes_the_first_examples(cli):
    icl = only(cli, task_config(icl=icl_section("a", k=1))).icl
    assert [example.output for example in icl.examples(icl.setups[0])] == ["a demo\n#### 0"]


# T44: `k` larger than the setup uses every example it has
def test_k_larger_than_the_setup_uses_every_example(cli):
    icl = only(cli, task_config(icl=icl_section("a", k=9))).icl
    assert len(icl.examples(icl.setups[0])) == 2


# "`icl.k`" must be a positive integer
@pytest.mark.parametrize("k", [0, -1, "two"])
def test_invalid_k_is_an_error(cli, k):
    with pytest.raises(ConfigError, match="k"):
        load(cli, task_config(icl=icl_section("a", k=k)))


# "`num_solutions` may be set in `defaults` or per task"
def test_num_solutions_from_defaults_and_from_a_task(cli):
    config = multi_config("gsm8k", "mmlu", defaults={"num_solutions": 3})
    config["tasks"]["mmlu"]["num_solutions"] = 7
    tasks = load(cli, config).tasks
    assert tasks["gsm8k"].num_solutions == 3
    assert tasks["mmlu"].num_solutions == 7


# "`num_solutions`" defaults to one solution per input
def test_num_solutions_defaults_to_one(cli):
    assert only(cli, task_config()).num_solutions == 1


# "`num_solutions`" must be a positive integer
@pytest.mark.parametrize("value", [0, -2, 1.5])
def test_invalid_num_solutions_is_an_error(cli, value):
    with pytest.raises(ConfigError, match="num_solutions"):
        load(cli, task_config(num_solutions=value))


# "CLI flags override config values" - `--num-solutions`, `--icl-k`, `--icl-strategy`
def test_cli_flags_override_the_icl_and_solution_config(cli):
    config = task_config(icl=SPEC_ICL, num_solutions=2)
    task = only(cli, config, num_solutions=4, icl_k=1, icl_strategy="random")
    assert task.num_solutions == 4
    assert task.icl.k == 1
    assert task.icl.strategy == "random"


# "CLI flags override config values" for every selected task
def test_cli_flags_reach_every_selected_task(cli):
    config = multi_config("gsm8k", "mmlu", defaults={"icl": icl_section("a", "b")})
    tasks = load(cli, config, num_solutions=3, icl_strategy="round_robin").tasks
    assert {task.num_solutions for task in tasks.values()} == {3}
    assert {task.icl.strategy for task in tasks.values()} == {"round_robin"}


# T55: `--icl-k` and `--icl-strategy` do not create ICL for a task without setups
def test_icl_flags_do_not_invent_setups(cli):
    assert only(cli, task_config(), icl_k=2, icl_strategy="random").icl is None


# "if `max_attempts` is omitted for rejection, default it to `3 * num_solutions`"
def test_max_attempts_defaults_to_three_times_num_solutions(cli):
    config = task_config(
        generation={"scheme": "rejection", "temperature": 0.7}, num_solutions=4
    )
    assert only(cli, config).generation.max_attempts == 12


# "`max_attempts` applies to rejection sampling in this part"
def test_configured_max_attempts_is_kept(cli):
    config = task_config(
        generation={"scheme": "rejection", "temperature": 0.7, "n": 5, "max_attempts": 15},
        num_solutions=5,
    )
    assert only(cli, config).generation.max_attempts == 15


# "`max_attempts`" must be a positive integer
def test_invalid_max_attempts_is_an_error(cli):
    config = task_config(generation={"scheme": "rejection", "temperature": 0.7, "max_attempts": 0})
    with pytest.raises(ConfigError, match="max_attempts"):
        load(cli, config)


# "ICL examples ... rendered with the task's `prompt.user` template" - an example
# that cannot be rendered is caught before any request is sent
def test_example_missing_a_template_field_is_an_error(cli, static_api):
    server = static_api("#### 5")
    config = task_config(
        api_url=server.url,
        prompt={"user": "{question} ({topic})"},
        icl=icl_section("a"),
    )
    run = cli.run(config, [{"question": "What is 2 + 3?", "topic": "math", "answer": "5"}])
    assert run.returncode == 1
    assert "topic" in run.stderr
    assert server.log.calls == []
