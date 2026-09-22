"""Which setup each attempt uses: `fixed`, `random`, `round_robin`, greedy."""

from __future__ import annotations

from conftest import icl_setup, make_config, setups_used

ROW = [{"question": "What is 15 + 27?", "answer": "42"}]
SETUPS = [icl_setup("A", "#### 1"), icl_setup("B", "#### 2"), icl_setup("C", "#### 3")]


def rejection_config(server_url, setups, max_attempts, **icl):
    """A rejection task whose responses never pass, so it uses every attempt."""
    return make_config(
        server_url,
        generation={
            "scheme": "rejection",
            "temperature": 0.7,
            "max_attempts": max_attempts,
        },
        icl={"setups": setups, **icl},
    )


# Spec: "`fixed`: always use the first setup".
def test_fixed_always_uses_the_first_setup(servers, run_cli):
    server = servers(contents=["#### 0"])
    config = rejection_config(server.url, SETUPS, 3, strategy="fixed")
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert setups_used(server) == ["A", "A", "A"]


# Spec: "`round_robin`: cycle through setups in order across attempts" -- the
# worked example with setups [A, B, C] over five attempts.
def test_round_robin_cycles_in_declared_order(servers, run_cli):
    server = servers(contents=["#### 0"])
    config = rejection_config(server.url, SETUPS, 5, strategy="round_robin")
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert setups_used(server) == ["A", "B", "C", "A", "B"]


# Spec: "`random`: choose a setup independently for each attempt" -- over many
# attempts both setups are picked.
def test_random_varies_across_attempts(servers, run_cli):
    server = servers(contents=["#### 0"])
    config = rejection_config(server.url, SETUPS[:2], 24, strategy="random")
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert set(setups_used(server)) == {"A", "B"}


# Spec: `icl.strategy` is optional, and the first setup is the natural default.
# (T38)
def test_strategy_defaults_to_fixed(servers, run_cli):
    server = servers(contents=["#### 0"])
    config = rejection_config(server.url, SETUPS, 3)
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert setups_used(server) == ["A", "A", "A"]


# Spec: "for `greedy` with ICL and `num_solutions > 1`, selection ignores the
# above strategy and instead walks setups in declared order, at most once per
# setup".
def test_greedy_walks_setups_in_order_ignoring_the_strategy(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = make_config(
        server.url,
        num_solutions=3,
        icl={"setups": SETUPS, "strategy": "random"},
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert setups_used(server) == ["A", "B", "C"]
    assert [item["icl_setup"] for item in result.rows[0]["output"]] == ["A", "B", "C"]


# Spec: "greedy with ICL: generate at temperature `0` once per selected setup".
def test_greedy_generates_at_temperature_zero(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = make_config(server.url, num_solutions=2, icl={"setups": SETUPS})
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert {payload["temperature"] for payload in server.payloads} == {0.0}


# Spec: "if there are two setups and `num_solutions: 5`, produce at most two
# solutions" and "do not retry the same greedy setup to manufacture additional
# outputs".
def test_greedy_is_capped_by_the_number_of_setups(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = make_config(server.url, num_solutions=5, icl={"setups": SETUPS[:2]})
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 2
    assert len(result.rows[0]["output"]) == 2
    assert result.rows[0]["result"]["attempts"] == 2


# Spec: the ordered walk is only "for `greedy` with ICL and `num_solutions >
# 1`", so a single-solution greedy run follows the strategy. (T57)
def test_single_solution_greedy_follows_the_strategy(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = make_config(
        server.url, num_solutions=1, icl={"setups": SETUPS, "strategy": "fixed"}
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert setups_used(server) == ["A"]


# Spec: "`round_robin`: cycle through setups in order across attempts" -- the
# cycle restarts for each input row. (T46)
def test_round_robin_restarts_for_each_row(servers, run_cli):
    server = servers(contents=["#### 0"], workers=1)
    config = rejection_config(server.url, SETUPS, 2, strategy="round_robin")
    rows = [{"question": f"q{index}", "answer": "42"} for index in range(2)]
    result = run_cli(config, rows)
    assert result.exit_code == 0, result.stderr
    assert sorted(setups_used(server)) == ["A", "A", "B", "B"]
