"""Which setup each attempt uses: `fixed`, `random`, `round_robin`, and greedy."""

from __future__ import annotations

from tests.conftest import icl_section, meta_setups, setups_used, task_config

ROW = {"question": "What is 2 + 3?", "answer": "5"}


def sampling_config(server, *names: str, solutions: int, **icl_options) -> dict:
    """A sampled task drawing setups from the named ICL setups."""
    return task_config(
        api_url=server.url,
        generation={"scheme": "sample", "temperature": 0.7},
        icl=icl_section(*names, **icl_options),
        num_solutions=solutions,
    )


# "`fixed`: always use the first setup"
def test_fixed_always_uses_the_first_setup(cli, static_api):
    server = static_api("#### 5")
    config = sampling_config(server, "a", "b", "c", solutions=3, strategy="fixed")
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert meta_setups(run.rows[0]) == ["a", "a", "a"]


# "`round_robin`: cycle through setups in order across attempts"
# "attempt 1 uses A ... attempt 4 uses A, attempt 5 uses B"
def test_round_robin_cycles_setups_across_attempts(cli, static_api):
    server = static_api("#### 5")
    config = sampling_config(server, "a", "b", "c", solutions=5, strategy="round_robin")
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert meta_setups(run.rows[0]) == ["a", "b", "c", "a", "b"]


# T40: the round-robin cursor restarts for every input row
def test_round_robin_restarts_for_each_row(cli, static_api):
    server = static_api("#### 5")
    config = sampling_config(server, "a", "b", "c", solutions=2, strategy="round_robin")
    run = cli.run(config, [ROW, ROW, ROW])
    assert run.returncode == 0, run.stderr
    assert [meta_setups(row) for row in run.rows] == [["a", "b"]] * 3


# "`random`: choose a setup independently for each attempt"
def test_random_varies_setups_across_attempts(cli, static_api):
    server = static_api("#### 5")
    config = sampling_config(server, "a", "b", solutions=20, strategy="random")
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    chosen = meta_setups(run.rows[0])
    assert len(chosen) == 20
    assert set(chosen) == {"a", "b"}


# "for `greedy` with ICL and `num_solutions > 1`, selection ignores the above
#  strategy and instead walks setups in declared order, at most once per setup"
def test_greedy_walks_setups_in_declared_order(cli, static_api):
    server = static_api("#### 5")
    config = task_config(
        api_url=server.url,
        icl=icl_section("a", "b", "c", strategy="fixed"),
        num_solutions=3,
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert setups_used(server) == ["a", "b", "c"]
    assert meta_setups(run.rows[0]) == ["a", "b", "c"]


# "Greedy cap: if there are two setups and `num_solutions: 5`, produce at most
#  two solutions" / "do not retry the same greedy setup"
def test_greedy_never_repeats_a_setup(cli, static_api):
    server = static_api("#### 5")
    config = task_config(api_url=server.url, icl=icl_section("a", "b"), num_solutions=5)
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 2
    assert len(run.rows[0]["output"]) == 2
    assert meta_setups(run.rows[0]) == ["a", "b"]


# "greedy ... generate at temperature `0` once per selected setup"
def test_greedy_generates_at_temperature_zero(cli, static_api):
    server = static_api("#### 5")
    config = task_config(api_url=server.url, icl=icl_section("a", "b"), num_solutions=2)
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert [body["temperature"] for body in server.log.bodies] == [0.0, 0.0]


# T45: with `num_solutions: 1` greedy keeps following the configured strategy
def test_single_solution_greedy_uses_the_strategy(cli, static_api):
    server = static_api("#### 5")
    config = task_config(
        api_url=server.url,
        icl=icl_section("a", "b", strategy="round_robin"),
        num_solutions=1,
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 1
    assert meta_setups(run.rows[0]) == ["a"]


# "`rejection` with ICL" draws its setups from the configured strategy
def test_rejection_follows_the_strategy_across_attempts(cli, static_api):
    server = static_api("#### 9")  # never passes, so the budget is spent
    config = task_config(
        api_url=server.url,
        generation={"scheme": "rejection", "temperature": 0.8, "max_attempts": 4},
        icl=icl_section("a", "b", "c", strategy="round_robin"),
        num_solutions=2,
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert meta_setups(run.rows[0]) == ["a", "b", "c", "a"]


# "`icl_setup` is the chosen setup name, or `null` when no ICL is configured"
def test_setups_are_null_without_icl(cli, static_api):
    server = static_api("#### 5")
    config = task_config(
        api_url=server.url,
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=2,
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert meta_setups(run.rows[0]) == [None, None]
    assert setups_used(server) == [None, None]
