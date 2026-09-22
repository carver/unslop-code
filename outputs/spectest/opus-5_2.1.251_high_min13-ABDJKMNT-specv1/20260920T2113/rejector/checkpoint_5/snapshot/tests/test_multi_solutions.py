"""Scheme behaviour once a task asks for more than one solution per input."""

from __future__ import annotations

from tests.conftest import icl_section, setups_used, task_config
from tests.fake_api import error, ok

ROW = {"question": "What is 2 + 3?", "answer": "5"}


def solutions_config(server, scheme: str, solutions: int, generation=None, **overrides) -> dict:
    """A task asking for ``solutions`` solutions under ``scheme``."""
    base = {"scheme": scheme} if scheme == "greedy" else {"scheme": scheme, "temperature": 0.7}
    return task_config(
        api_url=server.url,
        generation={**base, **(generation or {})},
        num_solutions=solutions,
        **overrides,
    )


def passing_then_failing(*passing: int):
    """Responder whose numbered requests in ``passing`` answer the expected 5."""

    def respond(index, body):
        return ok("#### 5") if index in passing else ok("#### 9")

    return respond


# "greedy with ICL: generate at temperature 0 once per selected setup and stop
#  when num_solutions solutions are collected"
def test_greedy_stops_once_enough_solutions_are_collected(cli, static_api):
    server = static_api("#### 5")
    config = solutions_config(server, "greedy", 2, icl=icl_section("a", "b", "c", "d"))
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 2
    assert len(run.rows[0]["output"]) == 2


# "stop when ... all setups are exhausted; because the same setup is
#  deterministic, the maximum number of produced solutions is the number of
#  available setups"
def test_greedy_is_capped_by_the_number_of_setups(cli, static_api):
    server = static_api("#### 5")
    config = solutions_config(server, "greedy", 5, icl=icl_section("a", "b"))
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"] == {"passed": 2, "failed": 0, "attempts": 2}


# "stop when num_solutions solutions are collected" - an attempt that produced
# nothing is not a solution, so the next setup still runs
def test_greedy_continues_past_a_failed_call(cli, api):
    server = api(lambda index, body: error(500) if index < 3 else ok("#### 5"))
    config = solutions_config(server, "greedy", 2, icl=icl_section("a", "b"))
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert setups_used(server) == ["a"] * 3 + ["b"]  # setup a burned its retries
    assert run.rows[0]["result"] == {"passed": 1, "failed": 1, "attempts": 2}


# T41: greedy without ICL has one prompt, so it produces at most one solution
def test_greedy_without_icl_makes_one_attempt(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(solutions_config(server, "greedy", 4), [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 1
    assert len(run.rows[0]["output"]) == 1


# "sample with ICL: make one sampled generation per requested solution using the
#  chosen ICL strategy"
def test_sample_with_icl_makes_one_generation_per_solution(cli, static_api):
    server = static_api("#### 5")
    config = solutions_config(server, "sample", 3, icl=icl_section("a", "b", strategy="round_robin"))
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert setups_used(server) == ["a", "b", "a"]
    assert len(run.rows[0]["output"]) == 3


# "sample with ICL: ... evaluation does not gate whether a solution is included"
def test_sample_keeps_solutions_that_fail_evaluation(cli, static_api):
    server = static_api("#### 9")
    config = solutions_config(server, "sample", 3, icl=icl_section("a"))
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert len(run.rows[0]["output"]) == 3
    assert run.rows[0]["result"] == {"passed": 0, "failed": 3, "attempts": 3}


# "sample without ICL: make num_solutions independent sampled requests"
def test_sample_without_icl_repeats_the_same_prompt(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(solutions_config(server, "sample", 4), [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 4
    assert {body["temperature"] for body in server.log.bodies} == {0.7}
    assert len(set(server.log.user_prompts)) == 1


# "rejection with ICL: keep generating and evaluating until num_solutions
#  passing solutions have been collected"
def test_rejection_collects_several_passing_solutions(cli, api):
    server = api(passing_then_failing(1, 3))
    config = solutions_config(
        server, "rejection", 2,
        generation={"max_attempts": 10}, icl=icl_section("a", "b", strategy="round_robin"),
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 4  # stops as soon as the second pass arrives
    assert run.rows[0]["result"] == {"passed": 2, "failed": 2, "attempts": 4}
    assert [item["icl_setup"] for item in run.rows[0]["output"]] == ["b", "b"]


# "Rejection partial result: if num_solutions: 5 and max_attempts: 10 and only
#  two attempts pass before the tenth attempt, write only those two passing
#  outputs, report passed: 2, failed: 8, and attempts: 10"
def test_rejection_reports_a_partial_result(cli, api):
    server = api(passing_then_failing(0, 4))
    config = solutions_config(server, "rejection", 5, generation={"max_attempts": 10})
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 8, "attempts": 10}
    assert len(server.log.calls) == 10


# "rejection without ICL: same as above, but every attempt uses the same prompt"
def test_rejection_without_icl_repeats_the_same_prompt(cli, static_api):
    server = static_api("#### 9")
    config = solutions_config(server, "rejection", 3, generation={"max_attempts": 4})
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert len(set(server.log.user_prompts)) == 1
    assert run.rows[0]["result"]["attempts"] == 4


# "if max_attempts is omitted for rejection, default it to 3 * num_solutions"
def test_rejection_defaults_its_attempt_budget(cli, static_api):
    server = static_api("#### 9")
    run = cli.run(solutions_config(server, "rejection", 2), [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 6
    assert run.rows[0]["result"] == {"passed": 0, "failed": 6, "attempts": 6}


# "legacy compatibility: when num_solutions == 1 and no ICL is configured, keep
#  the Part 1 rejection behavior (generation.n logical attempts) and do not
#  apply max_attempts"
def test_legacy_rejection_uses_n_and_ignores_max_attempts(cli, static_api):
    server = static_api("#### 9")
    config = task_config(
        api_url=server.url,
        generation={"scheme": "rejection", "temperature": 0.8, "n": 4, "max_attempts": 2},
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 4
    assert run.rows[0]["result"] == {"passed": False, "extracted_answer": None, "attempts": 4}


# "legacy compatibility" - one pass is still enough to stop
def test_legacy_rejection_still_stops_at_the_first_pass(cli, api):
    server = api(passing_then_failing(2))
    config = task_config(
        api_url=server.url,
        generation={"scheme": "rejection", "temperature": 0.8, "n": 5},
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 3
    assert run.rows[0]["output"] == {"solution": "#### 5"}


# "`max_attempts` applies to rejection sampling in this part" - T48: other
# schemes keep making exactly the requests their own rule describes
def test_max_attempts_does_not_apply_to_sample(cli, static_api):
    server = static_api("#### 9")
    config = solutions_config(server, "sample", 3, generation={"max_attempts": 1})
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 3


# T47: `generation.n` no longer caps attempts once num_solutions > 1
def test_generation_n_does_not_cap_multi_solution_rejection(cli, static_api):
    server = static_api("#### 9")
    config = solutions_config(server, "rejection", 2, generation={"n": 2, "max_attempts": 5})
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["attempts"] == 5


# "rejection with ICL" - with num_solutions 1 the ICL run still uses the
# max_attempts budget rather than Part 1's `n`
def test_single_solution_rejection_with_icl_uses_max_attempts(cli, static_api):
    server = static_api("#### 9")
    config = solutions_config(
        server, "rejection", 1, generation={"n": 7}, icl=icl_section("a"),
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 3  # 3 * num_solutions


# "New flags: --num-solutions <int>" / "CLI flags override config values"
def test_num_solutions_flag_overrides_the_config(cli, static_api):
    server = static_api("#### 5")
    config = solutions_config(server, "sample", 1)
    run = cli.run(config, [ROW], "--num-solutions", "3")
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 3
    assert len(run.rows[0]["output"]) == 3


# "New flags: --icl-strategy <fixed|random|round_robin>"
def test_icl_strategy_flag_overrides_the_config(cli, static_api):
    server = static_api("#### 5")
    config = solutions_config(server, "sample", 3, icl=icl_section("a", "b", strategy="fixed"))
    run = cli.run(config, [ROW], "--icl-strategy", "round_robin")
    assert run.returncode == 0, run.stderr
    assert setups_used(server) == ["a", "b", "a"]


# "New flags: --icl-k <int>"
def test_icl_k_flag_overrides_the_config(cli, static_api):
    server = static_api("#### 5")
    config = solutions_config(server, "greedy", 1, icl=icl_section("a", k=2))
    run = cli.run(config, [ROW], "--icl-k", "1")
    assert run.returncode == 0, run.stderr
    roles = [message["role"] for message in server.log.bodies[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
