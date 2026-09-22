"""Scheme behavior when more than one solution is requested."""

from __future__ import annotations

from conftest import base_task, icl_block, inline_setup, used_setup
from fake_api import FakeAPI, Reply, always, sequence

COT = inline_setup("chain_of_thought", "#### 4")
DIRECT = inline_setup("direct", "#### 4")
TERSE = inline_setup("terse", "4")

ROW = {"question": "real", "answer": "5"}


def solutions_task(api_url: str, scheme: str, num_solutions: int, **generation) -> dict:
    """A task asking for `num_solutions` solutions under `scheme`."""
    task = base_task(api_url)
    task["generation"] = {"scheme": scheme, **generation}
    task["num_solutions"] = num_solutions
    return task


def with_icl(task: dict, setups: list[dict], **settings) -> dict:
    task["icl"] = icl_block(setups, **settings)
    return task


# Spec: "`greedy` with ICL: generate at temperature `0` once per selected setup
# and stop when `num_solutions` solutions are collected or all setups are
# exhausted" / "if there are two setups and `num_solutions: 5`, produce at most
# two solutions"
# Context: Scheme behavior / Examples (greedy cap).
def test_greedy_produces_at_most_one_solution_per_setup(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = with_icl(solutions_task(api.url, "greedy", 5), [COT, DIRECT])
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 2
        assert [body["temperature"] for body in api.requests] == [0.0, 0.0]
    row = result.rows[0]
    assert len(row["output"]) == 2
    assert [item["icl_setup"] for item in row["output"]] == ["chain_of_thought", "direct"]


# Spec: "do not retry the same greedy setup to manufacture additional outputs"
# Context: Examples (greedy cap).
def test_greedy_never_repeats_a_setup(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = with_icl(solutions_task(api.url, "greedy", 6), [COT])
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 1
    assert len(result.rows[0]["output"]) == 1


# Spec: "stop when `num_solutions` solutions are collected"
# Context: Scheme behavior.
def test_greedy_stops_once_enough_solutions_are_collected(
    write_config, write_input, run_cli
):
    with FakeAPI(responder=always("#### 5")) as api:
        task = with_icl(solutions_task(api.url, "greedy", 2), [COT, DIRECT, TERSE])
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 2
    assert len(result.rows[0]["output"]) == 2


# Spec: "`sample` with ICL: make one sampled generation per requested solution
# using the chosen ICL strategy"
# Context: Scheme behavior.
def test_sample_with_icl_makes_one_request_per_solution(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = with_icl(
            solutions_task(api.url, "sample", 3, temperature=0.8),
            [COT, DIRECT],
            strategy="round_robin",
        )
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 3
        assert [used_setup(body) for body in api.requests] == [
            "chain_of_thought",
            "direct",
            "chain_of_thought",
        ]
    assert len(result.rows[0]["output"]) == 3


# Spec: "evaluation does not gate whether a solution is included"
# Context: Scheme behavior (`sample` with ICL).
def test_sample_includes_solutions_that_fail_evaluation(write_config, write_input, run_cli):
    script = [Reply(content="#### 5"), Reply(content="#### 9"), Reply(content="#### 5")]
    with FakeAPI(responder=sequence(script)) as api:
        task = with_icl(solutions_task(api.url, "sample", 3, temperature=0.8), [COT])
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
    row = result.rows[0]
    assert [item["solution"] for item in row["output"]] == ["#### 5", "#### 9", "#### 5"]
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}


# Spec: "`sample` without ICL: make `num_solutions` independent sampled
# requests"
# Context: Scheme behavior.
def test_sample_without_icl_makes_num_solutions_requests(
    write_config, write_input, run_cli
):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(solutions_task(api.url, "sample", 4, temperature=0.9))
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 4
        assert [body["temperature"] for body in api.requests] == [0.9] * 4
    row = result.rows[0]
    assert len(row["output"]) == 4
    assert all(item["icl_setup"] is None for item in row["output"])


# Spec: "`rejection` with ICL: keep generating and evaluating until
# `num_solutions` passing solutions have been collected"
# Context: Scheme behavior.
def test_rejection_stops_at_num_solutions_passes(write_config, write_input, run_cli):
    script = [
        Reply(content="#### 9"),  # fails
        Reply(content="#### 5"),  # passes
        Reply(content="#### 9"),  # fails
        Reply(content="#### 5"),  # passes: target reached
        Reply(content="#### 5"),  # never requested
    ]
    with FakeAPI(responder=sequence(script)) as api:
        task = with_icl(
            solutions_task(api.url, "rejection", 2, temperature=0.7, max_attempts=10), [COT]
        )
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 4
    row = result.rows[0]
    assert [item["solution"] for item in row["output"]] == ["#### 5", "#### 5"]
    assert row["result"] == {"passed": 2, "failed": 2, "attempts": 4}


# Spec: "`rejection` without ICL: same as above, but every attempt uses the
# same prompt"
# Context: Scheme behavior.
def test_rejection_without_icl_repeats_one_prompt(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = solutions_task(api.url, "rejection", 3, temperature=0.7)
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 3
        assert len({str(body["messages"]) for body in api.requests}) == 1
    assert [item["icl_setup"] for item in result.rows[0]["output"]] == [None, None, None]


# Spec: "if `num_solutions: 5` and `max_attempts: 10` and only two attempts
# pass before the tenth attempt, write only those two passing outputs, report
# `passed: 2`, `failed: 8`, and `attempts: 10`"
# Context: Examples (rejection partial result).
def test_rejection_partial_result(write_config, write_input, run_cli):
    def responder(index, body):
        return Reply(content="#### 5" if index in (2, 6) else "#### 9")

    with FakeAPI(responder=responder) as api:
        task = solutions_task(api.url, "rejection", 5, temperature=0.7, max_attempts=10)
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 10
    row = result.rows[0]
    assert [item["solution"] for item in row["output"]] == ["#### 5", "#### 5"]
    assert row["result"] == {"passed": 2, "failed": 8, "attempts": 10}
    assert len(row["meta"]) == 10


# Spec: "if `max_attempts` is omitted for rejection, default it to
# `3 * num_solutions`"
# Context: Multiple Solutions / Rules.
def test_rejection_default_attempt_budget(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 9"), delay=0.0) as api:
        task = solutions_task(api.url, "rejection", 4, temperature=0.7)
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 12
    assert result.rows[0]["result"]["attempts"] == 12


# Spec: "`max_attempts` applies to rejection sampling in this part"
# Context: Multiple Solutions / Rules; the budget caps the attempt loop.
def test_max_attempts_caps_the_attempt_loop(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 9")) as api:
        task = solutions_task(api.url, "rejection", 5, temperature=0.7, max_attempts=3)
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 3
    row = result.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 3, "attempts": 3}


# Spec: "legacy compatibility: when `num_solutions == 1` and no ICL is
# configured, keep the Part 1 rejection behavior (`generation.n` logical
# attempts) and do not apply `max_attempts`"
# Context: Multiple Solutions / Rules.
def test_legacy_rejection_uses_n_and_ignores_max_attempts(
    write_config, write_input, run_cli
):
    with FakeAPI(responder=always("#### 9")) as api:
        task = solutions_task(api.url, "rejection", 1, temperature=0.7, n=4, max_attempts=2)
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 4
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"] == {"passed": False, "extracted_answer": None, "attempts": 4}


# Spec: "legacy compatibility ... keep the Part 1 rejection behavior" — one
# passing attempt still ends the row.
# Context: Multiple Solutions / Rules.
def test_legacy_rejection_keeps_the_first_pass(write_config, write_input, run_cli):
    script = [Reply(content="#### 9"), Reply(content="#### 5"), Reply(content="#### 5")]
    with FakeAPI(responder=sequence(script)) as api:
        task = solutions_task(api.url, "rejection", 1, temperature=0.7, n=5)
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 2
    assert result.rows[0]["output"] == {"solution": "#### 5"}


# Spec: "`rejection` with ICL ... until `num_solutions` passing solutions"
# applies even when `num_solutions` is 1, so `max_attempts` governs the budget.
# Context: Multiple Solutions / Rules (ICL leaves the legacy path).
def test_icl_rejection_with_one_solution_uses_max_attempts(
    write_config, write_input, run_cli
):
    with FakeAPI(responder=always("#### 9")) as api:
        task = with_icl(
            solutions_task(api.url, "rejection", 1, temperature=0.7, n=9), [COT]
        )
        config = write_config(task)
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 3
    assert result.rows[0]["result"] == {"passed": 0, "failed": 3, "attempts": 3}


# Spec: "`greedy` with ICL ... at temperature `0`" — a greedy task without ICL
# has nothing to vary, so it still makes one attempt (see AMBIGUITIES T33).
# Context: Scheme behavior.
def test_greedy_without_icl_makes_one_attempt(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(solutions_task(api.url, "greedy", 4))
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 1
    assert len(result.rows[0]["output"]) == 1


# Spec: attempts that produce no response still count (see AMBIGUITIES T38);
# the row keeps going for the remaining requested solutions.
# Context: Output Changes / Rules.
def test_failed_api_attempts_do_not_end_a_multi_solution_row(
    write_config, write_input, run_cli
):
    script = [Reply(content="#### 5")] + [Reply(status=500)] * 3 + [Reply(content="#### 5")]
    with FakeAPI(responder=sequence(script)) as api:
        config = write_config(solutions_task(api.url, "sample", 3, temperature=0.8))
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 5
    row = result.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}
