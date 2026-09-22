"""Scheme behaviour when several solutions are requested per input."""

from __future__ import annotations

from conftest import (
    exact_match_task,
    icl_setup,
    make_config,
    make_multi_config,
    setups_used,
)

ROW = [{"question": "What is 15 + 27?", "answer": "42"}]
SETUPS = [icl_setup("A", "#### 1"), icl_setup("B", "#### 2")]


def sample_config(server_url, num_solutions, **overrides):
    return make_config(
        server_url,
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=num_solutions,
        **overrides,
    )


def rejection_config(server_url, num_solutions, **overrides):
    generation = {"scheme": "rejection", "temperature": 0.7}
    generation.update(overrides.pop("generation", {}))
    return make_config(
        server_url,
        generation=generation,
        num_solutions=num_solutions,
        **overrides,
    )


# Spec: "`sample` with ICL: make one sampled generation per requested solution
# using the chosen ICL strategy".
def test_sample_with_icl_makes_one_call_per_solution(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = sample_config(
        server.url, 3, icl={"setups": SETUPS, "strategy": "round_robin"}
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 3
    assert setups_used(server) == ["A", "B", "A"]
    assert len(result.rows[0]["output"]) == 3


# Spec: "`sample` with ICL: ... evaluation does not gate whether a solution is
# included".
def test_sample_includes_failing_solutions(servers, run_cli):
    server = servers(contents=["#### 42", "#### 0", "#### 42"], workers=1)
    config = sample_config(server.url, 3, icl={"setups": SETUPS})
    result = run_cli(config, ROW)
    row = result.rows[0]
    assert [item["solution"] for item in row["output"]] == [
        "#### 42",
        "#### 0",
        "#### 42",
    ]
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}


# Spec: "`sample` without ICL: make `num_solutions` independent sampled
# requests".
def test_sample_without_icl_makes_num_solutions_requests(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(sample_config(server.url, 4), ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 4
    assert len(result.rows[0]["output"]) == 4
    assert {payload["temperature"] for payload in server.payloads} == {0.7}


# Spec: "`rejection` with ICL: keep generating and evaluating until
# `num_solutions` passing solutions have been collected".
def test_rejection_stops_once_enough_solutions_pass(servers, run_cli):
    server = servers(contents=["#### 0", "#### 42", "#### 42", "#### 42"], workers=1)
    config = rejection_config(
        server.url, 2, generation={"max_attempts": 8}, icl={"setups": SETUPS}
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 3
    row = result.rows[0]
    assert [item["solution"] for item in row["output"]] == ["#### 42", "#### 42"]
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}


# Spec: "`rejection` without ICL: same as above, but every attempt uses the
# same prompt".
def test_rejection_without_icl_repeats_one_prompt(servers, run_cli):
    server = servers(contents=["#### 0"], workers=1)
    config = rejection_config(server.url, 2, generation={"max_attempts": 4})
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 4
    assert all(
        payload["messages"] == server.payloads[0]["messages"]
        for payload in server.payloads
    )


# Spec: "if `max_attempts` is omitted for rejection, default it to
# `3 * num_solutions`".
def test_max_attempts_defaults_to_three_times_num_solutions(servers, run_cli):
    server = servers(contents=["#### 0"], workers=1)
    result = run_cli(rejection_config(server.url, 2), ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 6
    assert result.rows[0]["result"]["attempts"] == 6


# Spec: the rejection partial-result example -- "`num_solutions: 5` and
# `max_attempts: 10`", two passes, "report `passed: 2`, `failed: 8`, and
# `attempts: 10`".
def test_rejection_partial_result(servers, run_cli):
    server = servers(contents=["#### 42", "#### 42", "#### 0"], workers=1)
    config = rejection_config(server.url, 5, generation={"max_attempts": 10})
    result = run_cli(config, ROW)
    row = result.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 8, "attempts": 10}


# Spec: "legacy compatibility: when `num_solutions == 1` and no ICL is
# configured, keep the Part 1 rejection behavior (`generation.n` logical
# attempts) and do not apply `max_attempts`".
def test_legacy_rejection_uses_n_and_ignores_max_attempts(servers, run_cli):
    server = servers(contents=["#### 0"], workers=1)
    config = make_config(
        server.url,
        generation={
            "scheme": "rejection",
            "temperature": 0.7,
            "n": 2,
            "max_attempts": 9,
        },
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 2
    assert result.rows[0]["result"]["attempts"] == 2


# Spec: legacy compatibility keeps the Part 1 row shape for a one-solution
# task with no ICL.
def test_legacy_row_keeps_the_part_1_shape(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(make_config(server.url, num_solutions=1), ROW)
    row = result.rows[0]
    assert row["output"] == {"solution": "#### 42"}
    assert row["result"] == {"passed": True, "extracted_answer": "42", "attempts": 1}
    assert isinstance(row["meta"], dict)


# Spec: "`num_solutions` may be set in `defaults` or per task".
def test_num_solutions_from_defaults(servers, run_multi):
    server = servers(contents=["#### 42"])
    config = make_multi_config(
        server.url,
        {"gsm8k": exact_match_task(generation={"scheme": "sample", "temperature": 0.7})},
        num_solutions=3,
    )
    result = run_multi(config, {"gsm8k": ROW})
    assert result.exit_code == 0, result.stderr
    assert len(result.rows("gsm8k")[0]["output"]) == 3


# Spec: "`num_solutions` may be set in `defaults` or per task" -- the task wins.
def test_task_num_solutions_overrides_defaults(servers, run_multi):
    server = servers(contents=["#### 42"])
    config = make_multi_config(
        server.url,
        {
            "gsm8k": exact_match_task(
                generation={"scheme": "sample", "temperature": 0.7}, num_solutions=2
            )
        },
        num_solutions=5,
    )
    result = run_multi(config, {"gsm8k": ROW})
    assert result.exit_code == 0, result.stderr
    assert len(result.rows("gsm8k")[0]["output"]) == 2


# Spec: `greedy` is deterministic and the spec only lets it repeat across
# setups, so without ICL it produces one solution. (T41)
def test_greedy_without_icl_produces_one_solution(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(make_config(server.url, num_solutions=4), ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 1
    assert len(result.rows[0]["output"]) == 1


# Spec: "`rejection` with ICL: keep generating and evaluating until ...
# `max_attempts` is exhausted" -- with ICL the attempts follow the strategy.
def test_rejection_attempts_follow_the_icl_strategy(servers, run_cli):
    server = servers(contents=["#### 0"], workers=1)
    config = rejection_config(
        server.url,
        1,
        generation={"max_attempts": 4},
        icl={"setups": SETUPS, "strategy": "round_robin"},
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert setups_used(server) == ["A", "B", "A", "B"]


# Spec: Part 2 merges "nested sections ... per task", which Part 3 gives no
# reason to exempt `icl` from. (T55)
def test_icl_may_come_from_defaults(servers, run_multi):
    server = servers(contents=["#### 42"])
    config = make_multi_config(
        server.url,
        {"gsm8k": exact_match_task()},
        icl={"setups": SETUPS, "strategy": "fixed"},
    )
    result = run_multi(config, {"gsm8k": ROW})
    assert result.exit_code == 0, result.stderr
    assert setups_used(server) == ["A"]
    assert result.rows("gsm8k")[0]["output"][0]["icl_setup"] == "A"
