"""Part 3: `fixed`, `random`, and `round_robin` setup selection."""
import pytest

from conftest import icl_block, make_config, marker_setups
from mock_api import MockAPI, always

ROWS = [{"question": "2+2?", "answer": "4"}]
SAMPLE = dict(scheme="sample", temperature=0.7)


def chosen(row):
    """The setup used by each attempt of a row, in attempt order."""
    return [m["icl_setup"] for m in row["meta"]]


def run_sample(run_tool, api, names, num_solutions, strategy=None, rows=ROWS):
    icl = icl_block(marker_setups(names), strategy=strategy)
    return run_tool(make_config(api_url=api.url, icl=icl,
                                num_solutions=num_solutions, **SAMPLE), rows)


# Spec: "`fixed`: always use the first setup"
# Context: Strategy behavior.
def test_fixed_always_uses_the_first_setup(run_tool):
    with MockAPI(always("#### 4")) as api:
        run = run_sample(run_tool, api, ["A", "B", "C"], 4, "fixed")
    assert run.returncode == 0, run.stderr
    assert chosen(run.rows[0]) == ["A", "A", "A", "A"]


def test_fixed_uses_declaration_order_not_alphabetical_order(run_tool):
    with MockAPI(always("#### 4")) as api:
        run = run_sample(run_tool, api, ["zeta", "alpha"], 2, "fixed")
    assert run.returncode == 0, run.stderr
    assert chosen(run.rows[0]) == ["zeta", "zeta"]


# Spec: "`round_robin`: cycle through setups in order across attempts"
# Spec (Examples): "Round-robin order with setups [A, B, C]: attempt 1 uses A,
#   attempt 2 uses B, attempt 3 uses C, attempt 4 uses A, attempt 5 uses B"
# Context: Strategy behavior / Examples.
def test_round_robin_cycles_through_setups_in_declared_order(run_tool):
    with MockAPI(always("#### 4")) as api:
        run = run_sample(run_tool, api, ["A", "B", "C"], 5, "round_robin")
    assert run.returncode == 0, run.stderr
    assert chosen(run.rows[0]) == ["A", "B", "C", "A", "B"]


def test_round_robin_with_one_setup_repeats_it(run_tool):
    with MockAPI(always("#### 4")) as api:
        run = run_sample(run_tool, api, ["only"], 3, "round_robin")
    assert run.returncode == 0, run.stderr
    assert chosen(run.rows[0]) == ["only", "only", "only"]


# T45: the cycle restarts for every input row.
def test_round_robin_restarts_for_each_row(run_tool):
    rows = [{"question": "a", "answer": "4"}, {"question": "b", "answer": "4"},
            {"question": "c", "answer": "4"}]
    with MockAPI(always("#### 4")) as api:
        run = run_sample(run_tool, api, ["A", "B", "C"], 2, "round_robin",
                         rows=rows)
    assert run.returncode == 0, run.stderr
    assert [chosen(r) for r in run.rows] == [["A", "B"]] * 3


# Spec: "`random`: choose a setup independently for each attempt"
# Context: Strategy behavior.
def test_random_only_ever_picks_declared_setups(run_tool):
    with MockAPI(always("#### 4")) as api:
        run = run_sample(run_tool, api, ["A", "B", "C"], 8, "random")
    assert run.returncode == 0, run.stderr
    assert set(chosen(run.rows[0])) <= {"A", "B", "C"}
    assert len(chosen(run.rows[0])) == 8


def test_random_is_not_pinned_to_a_single_setup(run_tool):
    # 40 independent draws from 3 setups: all-identical has probability ~1e-19.
    with MockAPI(always("#### 4")) as api:
        run = run_sample(run_tool, api, ["A", "B", "C"], 40, "random")
    assert run.returncode == 0, run.stderr
    assert len(set(chosen(run.rows[0]))) > 1


def test_random_with_one_setup_always_picks_it(run_tool):
    with MockAPI(always("#### 4")) as api:
        run = run_sample(run_tool, api, ["only"], 4, "random")
    assert run.returncode == 0, run.stderr
    assert chosen(run.rows[0]) == ["only"] * 4


# Spec: "for `greedy` with ICL and `num_solutions > 1`, selection ignores the
#        above strategy and instead walks setups in declared order, at most
#        once per setup"
# Context: Strategy behavior.
@pytest.mark.parametrize("strategy", ["fixed", "random", "round_robin"])
def test_greedy_multi_solution_walks_declared_order_whatever_the_strategy(
        run_tool, strategy):
    icl = icl_block(marker_setups(["A", "B", "C"]), strategy=strategy)
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, scheme="greedy",
                                   num_solutions=3), ROWS)
    assert run.returncode == 0, run.stderr
    assert chosen(run.rows[0]) == ["A", "B", "C"]


def test_greedy_multi_solution_uses_each_setup_at_most_once(run_tool):
    icl = icl_block(marker_setups(["A", "B"]), strategy="round_robin")
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, scheme="greedy",
                                   num_solutions=6), ROWS)
    assert run.returncode == 0, run.stderr
    assert chosen(run.rows[0]) == ["A", "B"]
    assert api.call_count == 2


# T44: with `num_solutions == 1` the override does not apply, so a `fixed` or
# `round_robin` greedy row uses the first setup by way of the strategy.
@pytest.mark.parametrize("strategy", ["fixed", "round_robin"])
def test_single_solution_greedy_uses_the_first_setup(run_tool, strategy):
    icl = icl_block(marker_setups(["A", "B", "C"]), strategy=strategy)
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, scheme="greedy",
                                   num_solutions=1), ROWS)
    assert run.returncode == 0, run.stderr
    assert chosen(run.rows[0]) == ["A"]
    assert api.call_count == 1


# Spec: rejection attempts also follow the configured strategy.
def test_rejection_attempts_follow_the_round_robin_cycle(run_tool):
    icl = icl_block(marker_setups(["A", "B"]), strategy="round_robin")
    with MockAPI(always("#### 0")) as api:      # never passes: 4 attempts
        run = run_tool(make_config(api_url=api.url, icl=icl,
                                   scheme="rejection", temperature=0.7,
                                   num_solutions=1, max_attempts=4), ROWS)
    assert run.returncode == 0, run.stderr
    assert chosen(run.rows[0]) == ["A", "B", "A", "B"]
