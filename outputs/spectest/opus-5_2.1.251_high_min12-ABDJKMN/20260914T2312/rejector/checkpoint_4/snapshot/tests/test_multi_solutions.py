"""Part 3: `num_solutions`, the new CLI flags and per-scheme attempt counts."""

import fake_api

from test_icl_config import icl, inline_setup


A_B = [inline_setup("A", "A-ex"), inline_setup("B", "B-ex")]
A_B_C = A_B + [inline_setup("C", "C-ex")]

SAMPLE = {"scheme": "sample", "temperature": 0.7}
REJECTION = {"scheme": "rejection", "temperature": 0.7}


def markers(api):
    return [rec.icl_marker for rec in api.requests]


# ---------------------------------------------------------------------------
# Spec: "New flags: --num-solutions <int>"
# Context: Multiple Solutions.
# ---------------------------------------------------------------------------
def test_num_solutions_flag(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task={"generation": SAMPLE},
                       extra=["--num-solutions", "3"], check=0)
    assert api.call_count == 3
    assert len(res.rows[0]["output"]) == 3


# ---------------------------------------------------------------------------
# Spec: "`num_solutions` may be set in `defaults` or per task"
# Context: Multiple Solutions.  Per task.
# ---------------------------------------------------------------------------
def test_num_solutions_per_task(run_multi):
    tasks = {"gsm8k": {"num_solutions": 3,
                       "generation": {"scheme": "sample", "temperature": 0.7}}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, tasks=tasks, check=0)
    assert len(res.task_rows("gsm8k")[0]["output"]) == 3
    assert res.summary["tasks"]["mmlu"]["total_api_calls"] == 1


# ---------------------------------------------------------------------------
# Spec: "`num_solutions` may be set in `defaults` or per task"
# Context: Multiple Solutions.  In `defaults`, inherited by every task.
# ---------------------------------------------------------------------------
def test_num_solutions_in_defaults(run_multi):
    # Only `num_solutions` is inherited here; each task keeps its own scheme.
    tasks = {"gsm8k": {"generation": SAMPLE}, "mmlu": {"generation": SAMPLE}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_multi(api, defaults={"num_solutions": 2}, tasks=tasks,
                        check=0)
    assert len(res.task_rows("gsm8k")[0]["output"]) == 2
    assert len(res.task_rows("mmlu")[0]["output"]) == 2


# ---------------------------------------------------------------------------
# Spec: "CLI flags override config values"
# Context: Multiple Solutions.  --num-solutions beats the config.
# ---------------------------------------------------------------------------
def test_num_solutions_flag_overrides_config(run_task):
    task = {"num_solutions": 2, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, extra=["--num-solutions", "4"], check=0)
    assert api.call_count == 4
    assert len(res.rows[0]["output"]) == 4


# ---------------------------------------------------------------------------
# Spec: "New flags: --icl-strategy <fixed|random|round_robin>" /
#       "CLI flags override config values"
# Context: Multiple Solutions.
# ---------------------------------------------------------------------------
def test_icl_strategy_flag_overrides_config(run_task):
    task = {"icl": icl(A_B_C, strategy="fixed"), "num_solutions": 3,
            "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, extra=["--icl-strategy", "round_robin"],
                 check=0)
    assert markers(api) == ["A-ex", "B-ex", "C-ex"]


# ---------------------------------------------------------------------------
# Spec: "New flags: --icl-k <int>" / "CLI flags override config values"
# Context: Multiple Solutions.
# ---------------------------------------------------------------------------
def test_icl_k_flag_overrides_config(run_task):
    task = {"icl": icl([inline_setup("cot", "ex-1", "ex-2", "ex-3")], k=3)}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, extra=["--icl-k", "1"], check=0)
    assert api.requests[0].assistant_contents == ["ex-1"]


# ---------------------------------------------------------------------------
# Spec: "--icl-strategy <fixed|random|round_robin>"
# Context: Multiple Solutions.  An unknown strategy on the CLI is an error.
# ---------------------------------------------------------------------------
def test_icl_strategy_flag_rejects_unknown_values(run_task):
    task = {"icl": icl(A_B)}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, extra=["--icl-strategy", "best"], check=1)
    assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "--num-solutions <int>"
# Context: Multiple Solutions.  A run must collect at least one solution.
# ---------------------------------------------------------------------------
def test_non_positive_num_solutions_exits_1(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task={"generation": SAMPLE},
                 extra=["--num-solutions", "0"], check=1)
        run_task(api, task={"num_solutions": -1, "generation": SAMPLE},
                 check=1)
    assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "if `max_attempts` is omitted for rejection, default it to
#        `3 * num_solutions`"
# Context: Multiple Solutions.
# ---------------------------------------------------------------------------
def test_max_attempts_defaults_to_three_times_num_solutions(run_task):
    task = {"num_solutions": 2, "generation": REJECTION}
    with fake_api.FakeAPI(fake_api.always("#### 9")) as api:
        res = run_task(api, task=task, check=0)
    assert api.call_count == 6
    assert res.rows[0]["result"]["attempts"] == 6


# ---------------------------------------------------------------------------
# Spec: "`max_attempts` applies to rejection sampling in this part"
# Context: Multiple Solutions.  An explicit budget caps the attempts.
# ---------------------------------------------------------------------------
def test_explicit_max_attempts_caps_rejection(run_task):
    task = {"num_solutions": 3,
            "generation": dict(REJECTION, max_attempts=4)}
    with fake_api.FakeAPI(fake_api.always("#### 9")) as api:
        res = run_task(api, task=task, check=0)
    assert api.call_count == 4
    assert res.rows[0]["result"]["attempts"] == 4


# ---------------------------------------------------------------------------
# Spec: "legacy compatibility: when `num_solutions == 1` and no ICL is
#        configured, keep the Part 1 rejection behavior (`generation.n` logical
#        attempts) and do not apply `max_attempts`"
# Context: Multiple Solutions.
# ---------------------------------------------------------------------------
def test_legacy_rejection_uses_n_and_ignores_max_attempts(run_task):
    task = {"generation": dict(REJECTION, n=4, max_attempts=2)}
    with fake_api.FakeAPI(fake_api.always("#### 9")) as api:
        res = run_task(api, task=task, check=0)
    assert api.call_count == 4
    assert res.rows[0]["result"]["attempts"] == 4
    # ... and the Part 1 row shape survives.
    assert isinstance(res.rows[0]["result"]["passed"], bool)


# ---------------------------------------------------------------------------
# Spec: "`max_attempts` applies to rejection sampling in this part"
# Context: Multiple Solutions; T60.  Other schemes ignore it.
# ---------------------------------------------------------------------------
def test_max_attempts_does_not_apply_to_sample(run_task):
    task = {"num_solutions": 4, "generation": dict(SAMPLE, max_attempts=2)}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert api.call_count == 4
    assert res.rows[0]["result"]["attempts"] == 4


# ---------------------------------------------------------------------------
# Spec: "`greedy` with ICL: generate at temperature `0` once per selected setup
#        and stop when `num_solutions` solutions are collected or all setups
#        are exhausted"
# Context: Scheme behavior.  Stop on `num_solutions` first.
# ---------------------------------------------------------------------------
def test_greedy_with_icl_stops_at_num_solutions(run_task):
    task = {"icl": icl(A_B_C), "num_solutions": 2,
            "generation": {"scheme": "greedy"}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert markers(api) == ["A-ex", "B-ex"]
    assert len(res.rows[0]["output"]) == 2


# ---------------------------------------------------------------------------
# Spec: "generate at temperature `0` once per selected setup"
# Context: Scheme behavior.  Every greedy request is sent at temperature 0.
# ---------------------------------------------------------------------------
def test_greedy_with_icl_sends_temperature_zero(run_task):
    task = {"icl": icl(A_B), "num_solutions": 2,
            "generation": {"scheme": "greedy", "temperature": 0.9}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert [b["temperature"] for b in api.bodies()] == [0, 0]


# ---------------------------------------------------------------------------
# Spec: "because the same setup is deterministic, the maximum number of
#        produced solutions is the number of available setups" /
#       "if there are two setups and `num_solutions: 5`, produce at most two
#        solutions"
# Context: Scheme behavior; Examples (greedy cap).
# ---------------------------------------------------------------------------
def test_greedy_cap_is_the_number_of_setups(run_task):
    task = {"icl": icl(A_B), "num_solutions": 5,
            "generation": {"scheme": "greedy"}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert api.call_count == 2
    row = res.rows[0]
    assert len(row["output"]) == 2
    assert row["result"]["attempts"] == 2


# ---------------------------------------------------------------------------
# Spec: "stop when `num_solutions` solutions are collected or all setups are
#        exhausted"
# Context: Scheme behavior; T48.  A failing evaluation does not stop greedy
# from emitting the solution it produced.
# ---------------------------------------------------------------------------
def test_greedy_with_icl_emits_solutions_that_fail_evaluation(run_task):
    task = {"icl": icl(A_B), "num_solutions": 2,
            "generation": {"scheme": "greedy"}}
    with fake_api.FakeAPI(fake_api.always("#### 9")) as api:
        res = run_task(api, task=task, check=0)
    row = res.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}


# ---------------------------------------------------------------------------
# Spec: "Scheme behavior when `num_solutions > 1`" (no `greedy` without ICL
#        entry) / "do not retry the same greedy setup to manufacture additional
#        outputs"
# Context: Scheme behavior; T49.
# ---------------------------------------------------------------------------
def test_greedy_without_icl_produces_one_solution(run_task):
    task = {"num_solutions": 4, "generation": {"scheme": "greedy"}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert api.call_count == 1
    assert len(res.rows[0]["output"]) == 1


# ---------------------------------------------------------------------------
# Spec: "`sample` with ICL: make one sampled generation per requested solution
#        using the chosen ICL strategy"
# Context: Scheme behavior.
# ---------------------------------------------------------------------------
def test_sample_with_icl_makes_one_generation_per_solution(run_task):
    task = {"icl": icl(A_B, strategy="round_robin"), "num_solutions": 3,
            "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert markers(api) == ["A-ex", "B-ex", "A-ex"]
    assert len(res.rows[0]["output"]) == 3
    assert [b["temperature"] for b in api.bodies()] == [0.7, 0.7, 0.7]


# ---------------------------------------------------------------------------
# Spec: "evaluation does not gate whether a solution is included"
# Context: Scheme behavior (`sample` with ICL).
# ---------------------------------------------------------------------------
def test_sample_with_icl_includes_failing_solutions(run_task):
    task = {"icl": icl(A_B), "num_solutions": 3, "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.sequence(["#### 5", "#### 9", "#### 9"])) \
            as api:
        res = run_task(api, task=task, check=0)
    row = res.rows[0]
    assert [o["solution"] for o in row["output"]] == \
        ["#### 5", "#### 9", "#### 9"]
    assert row["result"] == {"passed": 1, "failed": 2, "attempts": 3}


# ---------------------------------------------------------------------------
# Spec: "`sample` without ICL: make `num_solutions` independent sampled
#        requests"
# Context: Scheme behavior.
# ---------------------------------------------------------------------------
def test_sample_without_icl_makes_num_solutions_requests(run_task):
    task = {"num_solutions": 3, "generation": SAMPLE}
    rows = [{"question": "What is 15 + 27?", "answer": "42"}]
    with fake_api.FakeAPI(fake_api.always("#### 42")) as api:
        res = run_task(api, task=task, rows=rows, check=0)
    assert api.call_count == 3
    assert {r.user_contents[-1] for r in api.requests} == {"What is 15 + 27?"}
    assert [o["icl_setup"] for o in res.rows[0]["output"]] == [None] * 3


# ---------------------------------------------------------------------------
# Spec: "`rejection` with ICL: keep generating and evaluating until
#        `num_solutions` passing solutions have been collected or
#        `max_attempts` is exhausted"
# Context: Scheme behavior.  Collecting enough passes ends the row early.
# ---------------------------------------------------------------------------
def test_rejection_stops_once_enough_solutions_pass(run_task):
    task = {"icl": icl(A_B, strategy="round_robin"), "num_solutions": 2,
            "generation": dict(REJECTION, max_attempts=10)}
    script = ["#### 5", "#### 9", "#### 5", "#### 5"]
    with fake_api.FakeAPI(fake_api.sequence(script)) as api:
        res = run_task(api, task=task, check=0)
    assert api.call_count == 3
    row = res.rows[0]
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}
    assert [o["icl_setup"] for o in row["output"]] == ["A", "A"]


# ---------------------------------------------------------------------------
# Spec: "Rejection sampling now aims to collect multiple passing solutions
#        instead of stopping at the first pass."
# Context: Intro.  Only passing generations are written.
# ---------------------------------------------------------------------------
def test_rejection_writes_only_passing_solutions(run_task):
    task = {"num_solutions": 2, "generation": dict(REJECTION, max_attempts=6)}
    script = ["#### 9", "#### 5", "#### 9", "#### 5"]
    with fake_api.FakeAPI(fake_api.sequence(script)) as api:
        res = run_task(api, task=task, check=0)
    row = res.rows[0]
    assert [o["solution"] for o in row["output"]] == ["#### 5", "#### 5"]
    assert row["result"] == {"passed": 2, "failed": 2, "attempts": 4}


# ---------------------------------------------------------------------------
# Spec: "`rejection` without ICL: same as above, but every attempt uses the
#        same prompt"
# Context: Scheme behavior.
# ---------------------------------------------------------------------------
def test_rejection_without_icl_repeats_the_same_prompt(run_task):
    task = {"num_solutions": 2, "generation": dict(REJECTION, max_attempts=3)}
    rows = [{"question": "What is 15 + 27?", "answer": "42"}]
    with fake_api.FakeAPI(fake_api.always("#### 9")) as api:
        run_task(api, task=task, rows=rows, check=0)
    assert api.call_count == 3
    assert all(r.messages == api.requests[0].messages for r in api.requests)
    assert markers(api) == [None, None, None]


# ---------------------------------------------------------------------------
# Spec: "if `num_solutions: 5` and `max_attempts: 10` and only two attempts
#        pass before the tenth attempt, write only those two passing outputs,
#        report `passed: 2`, `failed: 8`, and `attempts: 10`"
# Context: Examples (rejection partial result).
# ---------------------------------------------------------------------------
def test_rejection_partial_result_example(run_task):
    task = {"num_solutions": 5, "generation": dict(REJECTION, max_attempts=10)}
    script = ["#### 5", "#### 9", "#### 5"] + ["#### 9"] * 7
    with fake_api.FakeAPI(fake_api.sequence(script)) as api:
        res = run_task(api, task=task, check=0)
    assert api.call_count == 10
    row = res.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 8, "attempts": 10}
    assert len(row["meta"]) == 10


# ---------------------------------------------------------------------------
# Spec: "keep generating and evaluating until `num_solutions` passing solutions
#        have been collected or `max_attempts` is exhausted"
# Context: Scheme behavior; T51.  An attempt whose HTTP calls all fail is a
# spent attempt, not the end of the row.
# ---------------------------------------------------------------------------
def test_a_failed_attempt_does_not_end_a_multi_solution_row(run_task):
    task = {"num_solutions": 2, "generation": dict(REJECTION, max_attempts=3)}
    # Three 5xx responses exhaust the retries of attempt 1; attempts 2 and 3
    # then succeed and pass.
    with fake_api.FakeAPI(fake_api.fail_times(3, "#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert api.call_count == 5
    row = res.rows[0]
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}
    assert len(row["output"]) == 2
