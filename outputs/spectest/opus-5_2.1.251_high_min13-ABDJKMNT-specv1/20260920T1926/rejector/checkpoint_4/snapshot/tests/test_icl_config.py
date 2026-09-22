"""ICL configuration: setup shapes, example files, `k` and `strategy`."""

from __future__ import annotations

import json

import pytest
import yaml

from conftest import base_task, icl_block, inline_setup
from fake_api import FakeAPI, always

from taskrunner.config import ConfigError, build_run_config, load_config


def build(task: dict, **overrides):
    return build_run_config({"task": task}, overrides).tasks["gsm8k_solve"]


def write_examples(workdir, name: str, examples: list[str]) -> None:
    """Write raw JSONL lines into `<workdir>/icl/<name>`."""
    directory = workdir / "icl"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text("".join(line + "\n" for line in examples))


EXAMPLE_LINE = json.dumps({"input": {"question": "What is 10 / 2?"}, "output": "#### 5"})


# Spec: "Tasks may define named ICL setups" with `icl.setups` entries carrying
# a `name` and inline `examples`.
# Context: ICL Configuration; the spec's `chain_of_thought` / `direct` example.
def test_named_setups_with_inline_examples():
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block(
        [
            inline_setup("chain_of_thought", "Let me think step by step.\n#### 4", "#### 5"),
            inline_setup("direct", "#### 4", "#### 5"),
        ],
        k=2,
        strategy="round_robin",
    )
    icl = build(task).icl
    assert [setup.name for setup in icl.setups] == ["chain_of_thought", "direct"]
    assert icl.k == 2
    assert icl.strategy == "round_robin"


# Spec: "each example's `input`" is an object and its "`output`" a string.
# Context: ICL Configuration.
def test_inline_examples_keep_input_and_output():
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([inline_setup("direct", "#### 4")])
    example = build(task).icl.setups[0].examples[0]
    assert example.input == {"question": "direct q0"}
    assert example.output == "#### 4"


# Spec: "each setup has a `name` and exactly one of `examples` or `file`"
# Context: ICL Configuration / Rules.
def test_setup_without_a_name_is_an_error():
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([{"examples": [{"input": {"question": "q"}, "output": "a"}]}])
    with pytest.raises(ConfigError, match="name"):
        build(task)


def test_setup_with_both_examples_and_file_is_an_error():
    task = base_task("http://localhost:8000")
    setup = inline_setup("both", "#### 4")
    setup["file"] = "icl/other.jsonl"
    task["icl"] = icl_block([setup])
    with pytest.raises(ConfigError, match="exactly one"):
        build(task)


def test_setup_with_neither_examples_nor_file_is_an_error():
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([{"name": "empty"}])
    with pytest.raises(ConfigError, match="exactly one"):
        build(task)


# Spec: "Setups may also come from files" / "file paths are relative to the
# config file directory"
# Context: ICL Configuration / Rules.
def test_file_backed_setup_resolves_against_the_config_directory(workdir):
    # The example file sits next to the config, not next to the working directory.
    write_examples(workdir / "nested", "gsm8k_detailed.jsonl", [EXAMPLE_LINE])
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([{"name": "detailed", "file": "icl/gsm8k_detailed.jsonl"}], k=3)
    path = workdir / "nested" / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))

    setup = load_config(path, {}).tasks["gsm8k_solve"].icl.setups[0]
    assert setup.name == "detailed"
    assert setup.examples[0].input == {"question": "What is 10 / 2?"}
    assert setup.examples[0].output == "#### 5"


# Spec: file-backed setups are "valid JSONL where each non-empty line has
# `{"input": <object>, "output": <string>}`"
# Context: ICL Configuration / Rules; blank lines are skipped.
def test_blank_lines_in_an_example_file_are_skipped(workdir, write_config):
    write_examples(workdir, "d.jsonl", [EXAMPLE_LINE, "", EXAMPLE_LINE])
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([{"name": "detailed", "file": "icl/d.jsonl"}])
    config = write_config(task)
    assert len(load_config(config, {}).tasks["gsm8k_solve"].icl.setups[0].examples) == 2


# Spec: "malformed lines or missing keys must terminate the run with exit code
# 1 before any API requests are sent; malformed line errors include
# `not valid JSON`"
# Context: ICL Configuration / Rules.
def test_malformed_example_line_exits_1_before_any_request(
    workdir, write_config, write_input, run_cli
):
    write_examples(workdir, "d.jsonl", [EXAMPLE_LINE, "{not json"])
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([{"name": "detailed", "file": "icl/d.jsonl"}])
    with FakeAPI(responder=always("#### 5")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 0
    assert result.returncode == 1
    assert "not valid JSON" in result.stderr


def test_example_line_missing_output_exits_1(workdir, write_config, write_input, run_cli):
    write_examples(workdir, "d.jsonl", [json.dumps({"input": {"question": "q"}})])
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([{"name": "detailed", "file": "icl/d.jsonl"}])
    with FakeAPI(responder=always("#### 5")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 0
    assert result.returncode == 1


def test_example_line_with_a_non_string_output_exits_1(
    workdir, write_config, write_input, run_cli
):
    line = json.dumps({"input": {"question": "q"}, "output": 5})
    write_examples(workdir, "d.jsonl", [line])
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([{"name": "detailed", "file": "icl/d.jsonl"}])
    with FakeAPI(responder=always("#### 5")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 0
    assert result.returncode == 1


# Spec: "`icl.k` defaults to all examples in the selected setup"
# Context: ICL Configuration / Rules.
def test_k_defaults_to_every_example():
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([inline_setup("direct", "a", "b", "c")])
    assert build(task).icl.k is None


# Spec: "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"
# Context: ICL Configuration / Rules.
@pytest.mark.parametrize("strategy", ["fixed", "random", "round_robin"])
def test_every_documented_strategy_is_accepted(strategy):
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([inline_setup("direct", "a")], strategy=strategy)
    assert build(task).icl.strategy == strategy


def test_unknown_strategy_is_an_error():
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([inline_setup("direct", "a")], strategy="nearest")
    with pytest.raises(ConfigError, match="strategy"):
        build(task)


# Spec: the `icl` block is optional (see AMBIGUITIES T32 for the default
# strategy when it is present without one).
# Context: ICL Configuration.
def test_strategy_defaults_to_fixed():
    task = base_task("http://localhost:8000")
    task["icl"] = icl_block([inline_setup("direct", "a")])
    assert build(task).icl.strategy == "fixed"


def test_no_icl_section_means_no_icl():
    assert build(base_task("http://localhost:8000")).icl is None


# Spec: "`num_solutions` may be set in `defaults` or per task"
# Context: Multiple Solutions / Rules.
def test_num_solutions_from_defaults_and_task():
    from conftest import base_defaults, math_task

    document = {
        "defaults": base_defaults("http://localhost:8000", num_solutions=4),
        "tasks": {"gsm8k": math_task(), "other": math_task(num_solutions=2)},
    }
    config = build_run_config(document, {})
    assert config.tasks["gsm8k"].num_solutions == 4
    assert config.tasks["other"].num_solutions == 2


def test_num_solutions_defaults_to_one():
    assert build(base_task("http://localhost:8000")).num_solutions == 1


# Spec: "if `max_attempts` is omitted for rejection, default it to
# `3 * num_solutions`"
# Context: Multiple Solutions / Rules.
def test_max_attempts_defaults_to_three_times_num_solutions():
    task = base_task("http://localhost:8000")
    task["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 5}
    task["num_solutions"] = 5
    assert build(task).generation.max_attempts == 15


def test_configured_max_attempts_wins():
    task = base_task("http://localhost:8000")
    task["generation"] = {"scheme": "rejection", "temperature": 0.7, "max_attempts": 7}
    task["num_solutions"] = 5
    assert build(task).generation.max_attempts == 7
