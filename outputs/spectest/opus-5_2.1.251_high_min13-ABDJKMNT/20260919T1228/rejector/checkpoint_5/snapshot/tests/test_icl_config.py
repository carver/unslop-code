"""The `icl` block: setup shape, file-backed setups, `k`, and `strategy`."""

from __future__ import annotations

import json

import pytest

from conftest import icl_setup, make_config

ROW = [{"question": "What is 15 + 27?", "answer": "42"}]

JSONL_EXAMPLE = json.dumps(
    {"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\n#### 5"}
)


def icl_config(server_url, setups, **icl):
    """A greedy single-task config carrying an `icl` block."""
    return make_config(server_url, icl={"setups": setups, **icl})


# Spec: "each setup has a `name` and exactly one of `examples` or `file`" --
# a setup without a name cannot be used.
def test_setup_without_name_exits_1(server, run_cli):
    setup = icl_setup("direct", "#### 4")
    del setup["name"]
    result = run_cli(icl_config(server.url, [setup]), ROW)
    assert result.exit_code == 1
    assert "name" in result.stderr


# Spec: "each setup has ... exactly one of `examples` or `file`" -- both given.
def test_setup_with_examples_and_file_exits_1(server, run_cli):
    setup = {**icl_setup("direct", "#### 4"), "file": "icl/direct.jsonl"}
    result = run_cli(
        icl_config(server.url, [setup]), ROW, files={"icl/direct.jsonl": JSONL_EXAMPLE}
    )
    assert result.exit_code == 1


# Spec: "each setup has ... exactly one of `examples` or `file`" -- neither.
def test_setup_with_neither_examples_nor_file_exits_1(server, run_cli):
    result = run_cli(icl_config(server.url, [{"name": "direct"}]), ROW)
    assert result.exit_code == 1


# Spec: "Setups may also come from files" -- a file-backed setup contributes
# its examples to the prompt.
def test_file_backed_setup_supplies_examples(server, run_cli):
    config = icl_config(server.url, [{"name": "detailed", "file": "icl/detailed.jsonl"}])
    result = run_cli(config, ROW, files={"icl/detailed.jsonl": JSONL_EXAMPLE + "\n"})
    assert result.exit_code == 0, result.stderr
    assert server.payloads[0]["messages"][1:3] == [
        {"role": "user", "content": "What is 10 / 2?"},
        {"role": "assistant", "content": "10 divided by 2 is 5.\n#### 5"},
    ]


# Spec: "file paths are relative to the config file directory".
def test_file_path_is_relative_to_the_config_directory(server, run_cli):
    config = icl_config(server.url, [{"name": "detailed", "file": "icl/detailed.jsonl"}])
    result = run_cli(config, ROW, files={"icl/detailed.jsonl": JSONL_EXAMPLE})
    assert result.exit_code == 0, result.stderr


# Spec: "file-backed setups must be valid JSONL" -- a missing file stops the run.
def test_missing_file_exits_1(server, run_cli):
    config = icl_config(server.url, [{"name": "detailed", "file": "icl/missing.jsonl"}])
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert server.call_count == 0


# Spec: "malformed lines ... must terminate the run with exit code 1".
def test_malformed_jsonl_line_exits_1(server, run_cli):
    config = icl_config(server.url, [{"name": "detailed", "file": "icl/detailed.jsonl"}])
    result = run_cli(config, ROW, files={"icl/detailed.jsonl": JSONL_EXAMPLE + "\n{oops"})
    assert result.exit_code == 1


# Spec: "each non-empty line has `{"input": <object>, "output": <string>}`" --
# missing keys terminate the run.
@pytest.mark.parametrize(
    "line",
    [
        json.dumps({"input": {"question": "q"}}),
        json.dumps({"output": "#### 4"}),
        json.dumps({"input": "q", "output": "#### 4"}),
        json.dumps({"input": {"question": "q"}, "output": 4}),
    ],
)
def test_bad_example_line_exits_1(server, run_cli, line):
    config = icl_config(server.url, [{"name": "detailed", "file": "icl/detailed.jsonl"}])
    result = run_cli(config, ROW, files={"icl/detailed.jsonl": line})
    assert result.exit_code == 1


# Spec: malformed setups "must terminate the run ... before any API requests
# are sent".
def test_bad_file_sends_no_requests(server, run_cli):
    config = icl_config(server.url, [{"name": "detailed", "file": "icl/detailed.jsonl"}])
    result = run_cli(config, ROW, files={"icl/detailed.jsonl": "not json"})
    assert result.exit_code == 1
    assert server.call_count == 0


# Spec: the file format is JSONL of "each non-empty line", so blank lines are
# skipped rather than rejected. (T56)
def test_blank_lines_in_the_file_are_skipped(server, run_cli):
    config = icl_config(server.url, [{"name": "detailed", "file": "icl/detailed.jsonl"}])
    result = run_cli(config, ROW, files={"icl/detailed.jsonl": f"\n{JSONL_EXAMPLE}\n\n"})
    assert result.exit_code == 0, result.stderr
    assert len(server.payloads[0]["messages"]) == 4


# Spec: "`icl.k` defaults to all examples in the selected setup".
def test_k_defaults_to_every_example(server, run_cli):
    config = icl_config(server.url, [icl_setup("direct", "#### 1", "#### 2", "#### 3")])
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    # system + three example pairs + the row's user turn.
    assert len(server.payloads[0]["messages"]) == 8


# Spec: "if `k` is smaller than the number of examples in the setup, use the
# first `k`".
def test_k_takes_the_first_k_examples(server, run_cli):
    config = icl_config(
        server.url, [icl_setup("direct", "#### 1", "#### 2", "#### 3")], k=2
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    messages = server.payloads[0]["messages"]
    assert [message["content"] for message in messages[2:6:2]] == ["#### 1", "#### 2"]
    assert len(messages) == 6


# Spec: "`icl.k` defaults to all examples in the selected setup" -- a `k`
# larger than the setup can only use what is there. (T54)
def test_k_larger_than_the_setup_uses_every_example(server, run_cli):
    config = icl_config(server.url, [icl_setup("direct", "#### 1")], k=5)
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert len(server.payloads[0]["messages"]) == 4


# Spec: "`icl.strategy` is one of `fixed`, `random`, or `round_robin`".
def test_unknown_strategy_exits_1(server, run_cli):
    config = icl_config(server.url, [icl_setup("direct", "#### 4")], strategy="greedy")
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "strategy" in result.stderr


# Spec: `icl.k` counts examples, so it must be a positive integer. (T54)
@pytest.mark.parametrize("k", [0, -1, "two"])
def test_invalid_k_exits_1(server, run_cli, k):
    config = icl_config(server.url, [icl_setup("direct", "#### 4")], k=k)
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "k" in result.stderr


# Spec: an `icl` block is defined by its `setups`, so it needs at least one.
def test_empty_setups_exits_1(server, run_cli):
    result = run_cli(icl_config(server.url, []), ROW)
    assert result.exit_code == 1
    assert "setups" in result.stderr


# Spec: "each example's `input` is rendered with the task's `prompt.user`
# template" -- an example that cannot be rendered stops the run. (T52)
def test_example_missing_a_template_field_exits_1(server, run_cli):
    setup = {"name": "direct", "examples": [{"input": {"q": "2+2?"}, "output": "#### 4"}]}
    result = run_cli(icl_config(server.url, [setup]), ROW)
    assert result.exit_code == 1
    assert server.call_count == 0
