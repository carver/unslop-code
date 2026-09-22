"""ICL setup declaration: inline examples, JSONL files, `k`, and validation."""

from __future__ import annotations

import json

from fake_server import FakeAPIServer, always, assistants_of
from conftest import icl_config, icl_setup

ROW = {"question": "q", "answer": "5"}

SPEC_SETUPS = [
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
]


def _run(write_config, write_input, run_cli, config_map, rows=None):
    """Run one config against a server that always answers `#### 5`."""
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input(rows or [ROW]))
        result.payloads = api.payloads
    return result


def _write_jsonl(path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines))


# Spec: the worked config with two named inline setups, `k: 2` and a strategy
def test_spec_inline_setups_configuration_runs(write_config, write_input, run_cli):
    config_map = icl_config("", SPEC_SETUPS, k=2, strategy="round_robin")
    result = _run(write_config, write_input, run_cli, config_map)

    assert result.returncode == 0
    assert assistants_of(result.payloads[0]) == [
        "Let me think step by step.\n2 + 2 = 4\n#### 4",
        "Step by step:\nI start with 3 cats.\nI get 2 more.\n3 + 2 = 5\n#### 5",
    ]


# Spec: "Setups may also come from files" - `file:` in place of `examples:`
def test_file_backed_setup_supplies_the_examples(write_config, write_input, run_cli, workdir):
    _write_jsonl(
        workdir / "icl" / "gsm8k_detailed.jsonl",
        [json.dumps({"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\n#### 5"})],
    )
    config_map = icl_config("", [{"name": "detailed", "file": "icl/gsm8k_detailed.jsonl"}])
    result = _run(write_config, write_input, run_cli, config_map)

    assert result.returncode == 0
    assert assistants_of(result.payloads[0]) == ["10 divided by 2 is 5.\n#### 5"]


# Spec: "file paths are relative to the config file directory"
def test_file_paths_resolve_against_the_config_directory(write_config, write_input, run_cli, workdir):
    _write_jsonl(
        workdir / "nested" / "examples.jsonl",
        [json.dumps({"input": {"question": "q"}, "output": "nested answer"})],
    )
    config_map = icl_config("", [{"name": "detailed", "file": "examples.jsonl"}])
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map, name="nested/task.yaml")
        result = run_cli(config, write_input([ROW]))
        payloads = api.payloads

    assert result.returncode == 0
    assert assistants_of(payloads[0]) == ["nested answer"]


# Spec: "file-backed setups must be valid JSONL" - a malformed line fails
def test_malformed_jsonl_line_terminates_the_run(write_config, write_input, run_cli, workdir):
    _write_jsonl(workdir / "examples.jsonl", ['{"input": {"question": "q"}, "output": "ok"}', "{not json"])
    config_map = icl_config("", [{"name": "broken", "file": "examples.jsonl"}])

    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input([ROW]))
        call_count = len(api.requests)

    assert result.returncode == 1
    assert result.stderr.strip()
    # Spec: "must terminate the run with exit code 1 before any API requests are sent"
    assert call_count == 0


# Spec: "each non-empty line has {"input": <object>, "output": <string>}" -
# a missing `output` key
def test_example_file_line_without_output_terminates_the_run(write_config, write_input, run_cli, workdir):
    _write_jsonl(workdir / "examples.jsonl", ['{"input": {"question": "q"}}'])
    config_map = icl_config("", [{"name": "broken", "file": "examples.jsonl"}])
    result = _run(write_config, write_input, run_cli, config_map)
    assert result.returncode == 1


# Spec: "each non-empty line has {"input": <object>, ...}" - a missing `input`
def test_example_file_line_without_input_terminates_the_run(write_config, write_input, run_cli, workdir):
    _write_jsonl(workdir / "examples.jsonl", ['{"output": "#### 4"}'])
    config_map = icl_config("", [{"name": "broken", "file": "examples.jsonl"}])
    result = _run(write_config, write_input, run_cli, config_map)
    assert result.returncode == 1


# Spec: `input` must be an object and `output` a string
def test_example_file_line_with_wrong_types_terminates_the_run(write_config, write_input, run_cli, workdir):
    _write_jsonl(workdir / "examples.jsonl", ['{"input": "q", "output": 4}'])
    config_map = icl_config("", [{"name": "broken", "file": "examples.jsonl"}])
    result = _run(write_config, write_input, run_cli, config_map)
    assert result.returncode == 1


# Spec: "each non-empty line" - blank lines are not example lines
def test_blank_lines_in_an_example_file_are_ignored(write_config, write_input, run_cli, workdir):
    _write_jsonl(
        workdir / "examples.jsonl",
        ["", '{"input": {"question": "q"}, "output": "only answer"}', "  "],
    )
    config_map = icl_config("", [{"name": "detailed", "file": "examples.jsonl"}])
    result = _run(write_config, write_input, run_cli, config_map)

    assert result.returncode == 0
    assert assistants_of(result.payloads[0]) == ["only answer"]


# Spec: a `file` that does not exist cannot be loaded
def test_missing_example_file_terminates_the_run(write_config, write_input, run_cli):
    config_map = icl_config("", [{"name": "detailed", "file": "nope.jsonl"}])
    result = _run(write_config, write_input, run_cli, config_map)
    assert result.returncode == 1


# Spec: "each setup has a `name`"
def test_setup_without_a_name_is_rejected(write_config, write_input, run_cli):
    config_map = icl_config("", [{"examples": [{"input": {"question": "q"}, "output": "a"}]}])
    result = _run(write_config, write_input, run_cli, config_map)
    assert result.returncode == 1


# Spec: "exactly one of `examples` or `file`" - not both
def test_setup_with_both_examples_and_file_is_rejected(write_config, write_input, run_cli, workdir):
    _write_jsonl(workdir / "examples.jsonl", ['{"input": {"question": "q"}, "output": "a"}'])
    setup = icl_setup("both", "A-1")
    setup["file"] = "examples.jsonl"
    result = _run(write_config, write_input, run_cli, icl_config("", [setup]))
    assert result.returncode == 1


# Spec: "exactly one of `examples` or `file`" - not neither
def test_setup_with_neither_examples_nor_file_is_rejected(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, icl_config("", [{"name": "empty"}]))
    assert result.returncode == 1


# Spec: "icl.strategy is one of fixed, random, or round_robin"
def test_unknown_strategy_is_rejected(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1")], strategy="sorted")
    result = _run(write_config, write_input, run_cli, config_map)
    assert result.returncode == 1


# Spec: "icl.k defaults to all examples in the selected setup"
def test_k_defaults_to_every_example(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1", "A-2", "A-3")])
    result = _run(write_config, write_input, run_cli, config_map)
    assert assistants_of(result.payloads[0]) == ["A-1", "A-2", "A-3"]


# Spec: "if k is smaller than the number of examples in the setup, use the first k"
def test_k_smaller_than_the_setup_uses_the_first_k(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1", "A-2", "A-3")], k=2)
    result = _run(write_config, write_input, run_cli, config_map)
    assert assistants_of(result.payloads[0]) == ["A-1", "A-2"]


# Spec: `k` caps the examples used; a larger `k` cannot invent examples
def test_k_larger_than_the_setup_uses_every_example(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1", "A-2")], k=5)
    result = _run(write_config, write_input, run_cli, config_map)
    assert assistants_of(result.payloads[0]) == ["A-1", "A-2"]


# Spec: `k` applies to file-backed setups the same way (see AMBIGUITIES T48)
def test_k_applies_to_file_backed_setups(write_config, write_input, run_cli, workdir):
    _write_jsonl(
        workdir / "examples.jsonl",
        [json.dumps({"input": {"question": f"q{i}"}, "output": f"F-{i}"}) for i in range(3)],
    )
    config_map = icl_config("", [{"name": "detailed", "file": "examples.jsonl"}], k=2)
    result = _run(write_config, write_input, run_cli, config_map)
    assert assistants_of(result.payloads[0]) == ["F-0", "F-1"]


# Spec: "each example's input is rendered with the task's prompt.user template"
# - an example missing a templated field cannot be rendered (AMBIGUITIES T46)
def test_example_missing_a_template_field_is_rejected(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1")])
    config_map["task"]["prompt"]["user"] = "{question} about {topic}"
    rows = [{"question": "q", "topic": "sums", "answer": "5"}]
    result = _run(write_config, write_input, run_cli, config_map, rows=rows)
    assert result.returncode == 1
