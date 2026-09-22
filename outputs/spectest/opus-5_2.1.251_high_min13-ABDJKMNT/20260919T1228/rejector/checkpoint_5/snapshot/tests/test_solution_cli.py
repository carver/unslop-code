"""The `--num-solutions`, `--icl-strategy` and `--icl-k` flags."""

from __future__ import annotations

from conftest import icl_setup, make_config, setups_used

ROW = [{"question": "What is 15 + 27?", "answer": "42"}]
SETUPS = [icl_setup("A", "#### 1"), icl_setup("B", "#### 2")]


# Spec: new flag `--num-solutions <int>`, and "CLI flags override config
# values".
def test_num_solutions_flag_overrides_the_config(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = make_config(
        server.url,
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=2,
    )
    result = run_cli(config, ROW, "--num-solutions", "4")
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 4
    assert len(result.rows[0]["output"]) == 4


# Spec: new flag `--icl-strategy <fixed|random|round_robin>` overriding
# `icl.strategy`.
def test_icl_strategy_flag_overrides_the_config(servers, run_cli):
    server = servers(contents=["#### 0"], workers=1)
    config = make_config(
        server.url,
        generation={"scheme": "rejection", "temperature": 0.7, "max_attempts": 4},
        icl={"setups": SETUPS, "strategy": "fixed"},
    )
    result = run_cli(config, ROW, "--icl-strategy", "round_robin")
    assert result.exit_code == 0, result.stderr
    assert setups_used(server) == ["A", "B", "A", "B"]


# Spec: new flag `--icl-k <int>` overriding `icl.k`.
def test_icl_k_flag_overrides_the_config(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = make_config(
        server.url,
        icl={"setups": [icl_setup("A", "#### 1", "#### 2", "#### 3")], "k": 3},
    )
    result = run_cli(config, ROW, "--icl-k", "1")
    assert result.exit_code == 0, result.stderr
    assert len(server.payloads[0]["messages"]) == 4


# Spec: "`--icl-strategy <fixed|random|round_robin>`" -- other values are a
# usage error.
def test_unknown_icl_strategy_flag_exits_1(server, run_cli):
    config = make_config(server.url, icl={"setups": SETUPS})
    result = run_cli(config, ROW, "--icl-strategy", "best")
    assert result.exit_code == 1


# Spec: "`--num-solutions <int>`" -- a non-integer value is a usage error.
def test_non_integer_num_solutions_exits_1(server, run_cli):
    result = run_cli(make_config(server.url), ROW, "--num-solutions", "many")
    assert result.exit_code == 1


# Spec: `num_solutions` counts solutions, so it must be a positive integer.
def test_zero_num_solutions_exits_1(server, run_cli):
    result = run_cli(make_config(server.url), ROW, "--num-solutions", "0")
    assert result.exit_code == 1
    assert "num_solutions" in result.stderr


# Spec: the ICL flags configure `icl`, so a task with no `icl` block runs
# unchanged. (T51)
def test_icl_flags_are_inert_without_an_icl_block(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(
        make_config(server.url), ROW, "--icl-strategy", "random", "--icl-k", "2"
    )
    assert result.exit_code == 0, result.stderr
    assert result.rows[0]["output"] == {"solution": "#### 42"}


# Spec: "CLI flags override config values" -- `--num-solutions 1` against a
# config asking for more returns the Part 1 row format.
def test_num_solutions_one_restores_the_part_1_format(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = make_config(
        server.url,
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=3,
    )
    result = run_cli(config, ROW, "--num-solutions", "1")
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 1
    assert result.rows[0]["output"] == {"solution": "#### 42"}
