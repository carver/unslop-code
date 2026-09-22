"""Part 3: how each scheme produces multiple solutions."""
import threading

import pytest

from conftest import icl_block, make_config, marker_setups
from mock_api import MockAPI, always, chat_response


def sequence_per_row(mapping, default=("#### 0",)):
    """Respond with mapping[final user content][k] for that row's k-th call."""
    counts = {}
    lock = threading.Lock()

    def responder(payload, i):
        user = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                user = m.get("content", "")
        with lock:
            k = counts.get(user, 0)
            counts[user] = k + 1
        seq = mapping.get(user, default)
        item = seq[k] if k < len(seq) else seq[-1]
        if isinstance(item, int):
            return item, {"error": "boom"}
        return 200, chat_response(item)
    return responder


ROWS = [{"question": "q", "answer": "42"}]
SAMPLE = dict(scheme="sample", temperature=0.7)
REJECT = dict(scheme="rejection", temperature=0.7)


# Spec: "`sample` without ICL: make `num_solutions` independent sampled
#        requests"
# Context: Scheme behavior when num_solutions > 1.
def test_sample_without_icl_makes_one_request_per_solution(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=4, **SAMPLE),
                       ROWS)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 4
    row = run.rows[0]
    assert len(row["output"]) == 4
    assert row["result"]["attempts"] == 4
    assert all(o["icl_setup"] is None for o in row["output"])


def test_sample_without_icl_sends_the_same_prompt_every_time(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=3, **SAMPLE),
                       ROWS)
    assert run.returncode == 0, run.stderr
    assert len({repr(c["messages"]) for c in api.calls}) == 1
    assert [c["temperature"] for c in api.calls] == [0.7, 0.7, 0.7]


# Spec: "`sample` with ICL: make one sampled generation per requested solution
#        using the chosen ICL strategy; evaluation does not gate whether a
#        solution is included"
# Context: Scheme behavior when num_solutions > 1.
def test_sample_with_icl_keeps_solutions_that_fail_evaluation(run_tool):
    icl = icl_block(marker_setups(["A"]), strategy="fixed")
    responder = sequence_per_row({"q": ["#### 42", "#### 0", "#### 7"]})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, num_solutions=3,
                                   **SAMPLE), ROWS)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 3
    row = run.rows[0]
    assert [o["solution"] for o in row["output"]] == ["#### 42", "#### 0",
                                                      "#### 7"]
    assert [m["evaluation_passed"] for m in row["meta"]] == [True, False, False]


def test_sample_with_icl_makes_exactly_num_solutions_generations(run_tool):
    icl = icl_block(marker_setups(["A", "B"]), strategy="round_robin")
    with MockAPI(always("#### 0")) as api:      # nothing passes
        run = run_tool(make_config(api_url=api.url, icl=icl, num_solutions=5,
                                   **SAMPLE), ROWS)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 5
    assert len(run.rows[0]["output"]) == 5
    assert run.rows[0]["result"]["attempts"] == 5


# Spec: "`greedy` with ICL: generate at temperature `0` once per selected
#        setup and stop when `num_solutions` solutions are collected or all
#        setups are exhausted"
# Context: Scheme behavior when num_solutions > 1.
def test_greedy_with_icl_generates_at_temperature_zero(run_tool):
    icl = icl_block(marker_setups(["A", "B"]))
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, scheme="greedy",
                                   num_solutions=2), ROWS)
    assert run.returncode == 0, run.stderr
    assert [c["temperature"] for c in api.calls] == [0.0, 0.0]


def test_greedy_with_icl_stops_once_num_solutions_are_collected(run_tool):
    icl = icl_block(marker_setups(["A", "B", "C", "D"]))
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, scheme="greedy",
                                   num_solutions=2), ROWS)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2
    assert [o["icl_setup"] for o in run.rows[0]["output"]] == ["A", "B"]


# Spec: "because the same setup is deterministic, the maximum number of
#        produced solutions is the number of available setups"
# Spec (Examples, Greedy cap): "if there are two setups and num_solutions: 5,
#   produce at most two solutions / do not retry the same greedy setup to
#   manufacture additional outputs"
# Context: Scheme behavior / Examples.
def test_greedy_cap_is_the_number_of_setups(run_tool):
    icl = icl_block(marker_setups(["A", "B"]))
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, scheme="greedy",
                                   num_solutions=5), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert api.call_count == 2
    assert len(row["output"]) == 2
    assert row["result"]["attempts"] == 2


# T46: greedy records evaluation but does not use it to drop a solution.
def test_greedy_with_icl_keeps_a_failing_setups_output(run_tool):
    icl = icl_block(marker_setups(["A", "B"]))
    responder = sequence_per_row({"q": ["#### 0", "#### 42"]})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, scheme="greedy",
                                   num_solutions=2), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert [o["solution"] for o in row["output"]] == ["#### 0", "#### 42"]
    assert [m["evaluation_passed"] for m in row["meta"]] == [False, True]
    assert row["result"] == {"passed": 1, "failed": 1, "attempts": 2}


# T47: greedy without ICL has one deterministic prompt, so it produces one
# solution however many are requested.
def test_greedy_without_icl_produces_a_single_solution(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="greedy",
                                   num_solutions=4), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert api.call_count == 1
    assert len(row["output"]) == 1
    assert row["output"][0] == {"solution": "#### 42", "icl_setup": None}
    assert row["result"]["attempts"] == 1


# Spec: "`rejection` with ICL: keep generating and evaluating until
#        `num_solutions` passing solutions have been collected or
#        `max_attempts` is exhausted"
# Context: Scheme behavior when num_solutions > 1.
def test_rejection_collects_num_solutions_passing_and_stops(run_tool):
    icl = icl_block(marker_setups(["A"]))
    responder = sequence_per_row(
        {"q": ["#### 42", "#### 0", "#### 42", "#### 42", "#### 42"]})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, num_solutions=3,
                                   max_attempts=10, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert api.call_count == 4
    assert row["result"] == {"passed": 3, "failed": 1, "attempts": 4}
    assert [o["solution"] for o in row["output"]] == ["#### 42"] * 3


def test_rejection_drops_failing_attempts_from_the_output(run_tool):
    icl = icl_block(marker_setups(["A"]))
    responder = sequence_per_row({"q": ["#### 1", "#### 42", "#### 2",
                                        "#### 42"]})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, num_solutions=2,
                                   max_attempts=10, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert [o["solution"] for o in row["output"]] == ["#### 42", "#### 42"]
    assert row["result"]["attempts"] == 4


# Spec: "`rejection` without ICL: same as above, but every attempt uses the
#        same prompt"
# Context: Scheme behavior when num_solutions > 1.
def test_rejection_without_icl_repeats_the_same_prompt(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=3,
                                   max_attempts=10, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 3
    assert len({repr(c["messages"]) for c in api.calls}) == 1
    assert run.rows[0]["result"] == {"passed": 3, "failed": 0, "attempts": 3}


# Spec (Examples, Rejection partial result): "if num_solutions: 5 and
#   max_attempts: 10 and only two attempts pass before the tenth attempt,
#   write only those two passing outputs, report passed: 2, failed: 8, and
#   attempts: 10"
# Context: Examples.
def test_rejection_partial_result_example(run_tool):
    seq = ["#### 0"] * 10
    seq[2] = "#### 42"
    seq[6] = "#### 42"
    with MockAPI(sequence_per_row({"q": seq})) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=5,
                                   max_attempts=10, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert api.call_count == 10
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 8, "attempts": 10}


# Spec: "`max_attempts` applies to rejection sampling in this part"
# Context: Multiple Solutions rules.
def test_max_attempts_caps_rejection_attempts(run_tool):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=3,
                                   max_attempts=4, n=99, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 4
    assert run.rows[0]["result"]["attempts"] == 4


# Spec: "if `max_attempts` is omitted for rejection, default it to
#        `3 * num_solutions`"
# Context: Multiple Solutions rules.
@pytest.mark.parametrize("num_solutions", [2, 3])
def test_max_attempts_defaults_to_three_times_num_solutions(run_tool,
                                                            num_solutions):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   num_solutions=num_solutions, **REJECT),
                       ROWS)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 3 * num_solutions
    assert run.rows[0]["result"]["attempts"] == 3 * num_solutions


def test_max_attempts_default_applies_to_single_solution_icl_rejection(run_tool):
    icl = icl_block(marker_setups(["A"]))
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, num_solutions=1,
                                   **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 3
    assert run.rows[0]["result"]["attempts"] == 3


# T59: outside legacy mode `generation.n` no longer bounds the attempts.
def test_n_is_ignored_once_num_solutions_is_greater_than_one(run_tool):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, n=2, num_solutions=5,
                                   max_attempts=7, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 7


# Spec: "legacy compatibility: when `num_solutions == 1` and no ICL is
#        configured, keep the Part 1 rejection behavior (`generation.n`
#        logical attempts) and do not apply `max_attempts`"
# Context: Multiple Solutions rules.
def test_legacy_rejection_uses_n_attempts_and_ignores_max_attempts(run_tool):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, n=3, max_attempts=9,
                                   num_solutions=1, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    assert api.call_count == 3
    row = run.rows[0]
    assert row["output"] is None
    assert row["result"] == {"passed": False, "extracted_answer": None,
                             "attempts": 3}


def test_legacy_rejection_without_num_solutions_is_unchanged(run_tool):
    responder = sequence_per_row({"q": ["#### 0", "#### 42"]})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, n=5, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert api.call_count == 2
    assert row["output"] == {"solution": "#### 42"}
    assert row["result"]["passed"] is True
    assert isinstance(row["meta"], list) and len(row["meta"]) == 2
    assert "icl_setup" not in row["meta"][0]


# T58: a sample attempt whose request never succeeds is not topped up.
def test_sample_does_not_retry_an_attempt_that_returned_no_response(run_tool):
    seq = ["#### 42", 500, 500, 500, "#### 42"]
    with MockAPI(sequence_per_row({"q": seq})) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=3, **SAMPLE),
                       ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    # attempt 1 succeeds, attempt 2 burns three HTTP calls, attempt 3 succeeds.
    assert api.call_count == 5
    assert row["result"]["attempts"] == 3
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}
