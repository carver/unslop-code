"""Part 3: `fixed`, `random` and `round_robin` setup selection."""

import fake_api

from test_icl_config import icl, inline_setup


A_B_C = [inline_setup("A", "A-ex"), inline_setup("B", "B-ex"),
         inline_setup("C", "C-ex")]

SAMPLE = {"scheme": "sample", "temperature": 0.7}


def markers(api):
    """The setup marker of each recorded request, in arrival order."""
    return [rec.icl_marker for rec in api.requests]


def markers_for_row(api, question):
    """Markers of the requests whose final user turn is `question`."""
    return [rec.icl_marker for rec in api.requests
            if rec.user_contents[-1] == question]


# ---------------------------------------------------------------------------
# Spec: "`fixed`: always use the first setup"
# Context: Strategy behavior.
# ---------------------------------------------------------------------------
def test_fixed_always_uses_the_first_setup(run_task):
    task = {"icl": icl(A_B_C, strategy="fixed"), "num_solutions": 4,
            "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert markers(api) == ["A-ex"] * 4


# ---------------------------------------------------------------------------
# Spec: "`round_robin`: cycle through setups in order across attempts" /
#        "attempt 1 uses A, attempt 2 uses B, attempt 3 uses C, attempt 4 uses
#        A, attempt 5 uses B"
# Context: Strategy behavior; Examples.
# ---------------------------------------------------------------------------
def test_round_robin_cycles_through_setups_in_order(run_task):
    task = {"icl": icl(A_B_C, strategy="round_robin"), "num_solutions": 5,
            "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert markers(api) == ["A-ex", "B-ex", "C-ex", "A-ex", "B-ex"]


# ---------------------------------------------------------------------------
# Spec: "`round_robin`: cycle through setups in order across attempts"
# Context: Strategy behavior; T46.  "attempt" is the per-row attempt, so every
# row starts the cycle at the first setup.
# ---------------------------------------------------------------------------
def test_round_robin_restarts_for_each_row(run_task):
    rows = [{"question": "row-a", "answer": "5"},
            {"question": "row-b", "answer": "5"}]
    task = {"icl": icl(A_B_C, strategy="round_robin"), "num_solutions": 4,
            "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, rows=rows, check=0)
    for question in ("row-a", "row-b"):
        assert markers_for_row(api, question) == \
            ["A-ex", "B-ex", "C-ex", "A-ex"]


# ---------------------------------------------------------------------------
# Spec: "`random`: choose a setup independently for each attempt"
# Context: Strategy behavior.  Each attempt draws from the declared setups, and
# over many attempts the choice is not pinned to one setup.
# ---------------------------------------------------------------------------
def test_random_chooses_independently_per_attempt(run_task):
    task = {"icl": icl(A_B_C, strategy="random"), "num_solutions": 30,
            "generation": SAMPLE}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    seen = markers(api)
    assert len(seen) == 30
    assert set(seen) <= {"A-ex", "B-ex", "C-ex"}
    # P(all 30 attempts identical) = 3 * (1/3)**30.
    assert len(set(seen)) > 1


# ---------------------------------------------------------------------------
# Spec: "for `greedy` with ICL and `num_solutions > 1`, selection ignores the
#        above strategy and instead walks setups in declared order, at most
#        once per setup"
# Context: Strategy behavior.  Declared order even though `random` is set.
# ---------------------------------------------------------------------------
def test_greedy_walks_setups_in_declared_order_ignoring_strategy(run_task):
    task = {"icl": icl(A_B_C, strategy="random"), "num_solutions": 3,
            "generation": {"scheme": "greedy"}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert markers(api) == ["A-ex", "B-ex", "C-ex"]


# ---------------------------------------------------------------------------
# Spec: "walks setups in declared order, at most once per setup" /
#        "do not retry the same greedy setup to manufacture additional outputs"
# Context: Strategy behavior; Examples.  No setup is visited twice.
# ---------------------------------------------------------------------------
def test_greedy_visits_each_setup_at_most_once(run_task):
    task = {"icl": icl(A_B_C, strategy="round_robin"), "num_solutions": 9,
            "generation": {"scheme": "greedy"}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert markers(api) == ["A-ex", "B-ex", "C-ex"]


# ---------------------------------------------------------------------------
# Spec: "`round_robin`: cycle through setups in order across attempts"
# Context: Strategy behavior.  Rejection attempts follow the strategy too.
# ---------------------------------------------------------------------------
def test_rejection_attempts_follow_the_strategy(run_task):
    task = {"icl": icl(A_B_C, strategy="round_robin"),
            "generation": {"scheme": "rejection", "temperature": 0.7,
                           "max_attempts": 5}}
    # "#### 9" never matches the row's answer, so every attempt is spent.
    with fake_api.FakeAPI(fake_api.always("#### 9")) as api:
        run_task(api, task=task, check=0)
    assert markers(api) == ["A-ex", "B-ex", "C-ex", "A-ex", "B-ex"]


# ---------------------------------------------------------------------------
# Spec: "`fixed`: always use the first setup"
# Context: Strategy behavior.  A single-solution ICL run uses the strategy's
# first choice and makes one call.
# ---------------------------------------------------------------------------
def test_single_solution_icl_run_uses_the_first_setup(run_task):
    task = {"icl": icl(A_B_C, strategy="round_robin"),
            "generation": {"scheme": "greedy"}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert markers(api) == ["A-ex"]
    assert res.rows[0]["output"][0]["icl_setup"] == "A"
