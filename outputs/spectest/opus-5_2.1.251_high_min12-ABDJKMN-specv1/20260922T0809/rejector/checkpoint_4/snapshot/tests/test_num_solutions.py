"""Spec section: Part 3 / Multiple Solutions (scheme behaviour)."""
from __future__ import annotations

from conftest import (COT_SETUP, DIRECT_SETUP, TERSE_SETUP, base_config,
                      icl_config)
from mock_server import MockAPI, always, completion, sequence


ROW = {"question": "What is 15 + 27?", "answer": "42"}

MARKERS = {
    COT_SETUP["examples"][0]["output"]: "chain_of_thought",
    DIRECT_SETUP["examples"][0]["output"]: "direct",
    TERSE_SETUP["examples"][0]["output"]: "terse",
}


def used_setups(api):
    names = []
    for req in api.requests:
        shots = [m["content"] for m in req["messages"]
                 if m.get("role") == "assistant"]
        names.append(MARKERS.get(shots[0]) if shots else None)
    return names


# ---------------------------------------------------------------------------
# Phrase: "`greedy` with ICL: generate at temperature `0` once per selected
#          setup and stop when `num_solutions` solutions are collected or all
#          setups are exhausted"
# Context: Part 3 / Scheme behavior when num_solutions > 1.
# ---------------------------------------------------------------------------
def test_greedy_with_icl_walks_setups_in_declared_order(run_tool,
                                                        write_config,
                                                        write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP, DIRECT_SETUP, TERSE_SETUP],
            strategy="round_robin", num_solutions=3,
            generation={"scheme": "greedy"}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        names = used_setups(api)
        temps = [r["temperature"] for r in api.requests]
    assert res.returncode == 0, res
    assert names == ["chain_of_thought", "direct", "terse"]
    assert temps == [0.0, 0.0, 0.0]
    assert [o["icl_setup"] for o in res.rows[0]["output"]] == names


# Context: same phrase - stop as soon as `num_solutions` are collected, even
# with more setups available.
def test_greedy_stops_once_num_solutions_collected(run_tool, write_config,
                                                   write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP, DIRECT_SETUP, TERSE_SETUP],
            num_solutions=2, generation={"scheme": "greedy"}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
        names = used_setups(api)
    assert res.returncode == 0, res
    assert calls == 2
    assert names == ["chain_of_thought", "direct"]
    assert res.rows[0]["result"]["attempts"] == 2


# ---------------------------------------------------------------------------
# Phrase: "Greedy cap: if there are two setups and `num_solutions: 5`, produce
#          at most two solutions / do not retry the same greedy setup to
#          manufacture additional outputs"
# Context: Part 3 / Examples.
# ---------------------------------------------------------------------------
def test_greedy_cap_is_the_number_of_setups(run_tool, write_config,
                                            write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP, DIRECT_SETUP], num_solutions=5,
            generation={"scheme": "greedy"}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
        names = used_setups(api)
    assert res.returncode == 0, res
    assert calls == 2
    assert len(names) == len(set(names)) == 2
    row = res.rows[0]
    assert len(row["output"]) == 2
    assert row["result"]["attempts"] == 2


# ---------------------------------------------------------------------------
# Phrase: "`sample` with ICL: make one sampled generation per requested
#          solution using the chosen ICL strategy"
# Context: Part 3 / Scheme behavior when num_solutions > 1.
# ---------------------------------------------------------------------------
def test_sample_with_icl_makes_one_call_per_solution(run_tool, write_config,
                                                     write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP, DIRECT_SETUP], strategy="round_robin",
            num_solutions=4,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
        temps = {r["temperature"] for r in api.requests}
    assert res.returncode == 0, res
    assert calls == 4
    assert temps == {0.7}
    assert len(res.rows[0]["output"]) == 4


# Context: same phrase - "evaluation does not gate whether a solution is
# included": failing generations are still emitted as solutions.
def test_sample_with_icl_keeps_failing_solutions(run_tool, write_config,
                                                 write_input):
    responder = sequence(["#### 1", "#### 42", "#### 3"])
    with MockAPI(responder) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP], num_solutions=3,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 3
    row = res.rows[0]
    assert [o["solution"] for o in row["output"]] == ["#### 1", "#### 42",
                                                      "#### 3"]
    assert row["result"] == {"passed": 1, "failed": 2, "attempts": 3}


# ---------------------------------------------------------------------------
# Phrase: "`sample` without ICL: make `num_solutions` independent sampled
#          requests"
# Context: Part 3 / Scheme behavior when num_solutions > 1.
# ---------------------------------------------------------------------------
def test_sample_without_icl_makes_num_solutions_requests(run_tool,
                                                         write_config,
                                                         write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=3,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
        sent = api.requests
    assert res.returncode == 0, res
    assert calls == 3
    # Independent requests: the same prompt, no ICL turns.
    assert all([m["role"] for m in r["messages"]] == ["system", "user"]
               for r in sent)
    row = res.rows[0]
    assert len(row["output"]) == 3
    assert all(o["icl_setup"] is None for o in row["output"])


# ---------------------------------------------------------------------------
# Phrase: "`rejection` with ICL: keep generating and evaluating until
#          `num_solutions` passing solutions have been collected or
#          `max_attempts` is exhausted"
# Context: Part 3 / Scheme behavior when num_solutions > 1.
# ---------------------------------------------------------------------------
def test_rejection_collects_multiple_passing_solutions(run_tool, write_config,
                                                       write_input):
    responder = sequence(["#### 1", "#### 42", "#### 2", "#### 42",
                          "#### 42", "#### 42"])
    with MockAPI(responder) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP], num_solutions=3,
            generation={"scheme": "rejection", "temperature": 0.7,
                        "max_attempts": 10}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 5           # stops as soon as the third pass arrives
    row = res.rows[0]
    assert [o["solution"] for o in row["output"]] == ["#### 42"] * 3
    assert row["result"] == {"passed": 3, "failed": 2, "attempts": 5}


# Context: same phrase - only passing solutions are written out.
def test_rejection_only_writes_passing_solutions(run_tool, write_config,
                                                 write_input):
    responder = sequence(["#### 42", "#### 7", "#### 42"])
    with MockAPI(responder) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP], num_solutions=2,
            generation={"scheme": "rejection", "temperature": 0.7,
                        "max_attempts": 5}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert [o["solution"] for o in row["output"]] == ["#### 42", "#### 42"]
    assert row["result"]["attempts"] == 3


# ---------------------------------------------------------------------------
# Phrase: "Rejection partial result: if `num_solutions: 5` and
#          `max_attempts: 10` and only two attempts pass before the tenth
#          attempt, write only those two passing outputs, report `passed: 2`,
#          `failed: 8`, and `attempts: 10`"
# Context: Part 3 / Examples.
# ---------------------------------------------------------------------------
def test_rejection_partial_result(run_tool, write_config, write_input):
    def responder(req, i):
        # Attempts 3 and 6 (0-indexed 2 and 5) pass; everything else fails.
        return 200, completion("#### 42" if i in (2, 5) else "#### 0")

    with MockAPI(responder) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP], num_solutions=5,
            generation={"scheme": "rejection", "temperature": 0.7,
                        "max_attempts": 10}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 10
    row = res.rows[0]
    assert [o["solution"] for o in row["output"]] == ["#### 42", "#### 42"]
    assert row["result"] == {"passed": 2, "failed": 8, "attempts": 10}
    assert len(row["meta"]) == 10


# ---------------------------------------------------------------------------
# Phrase: "`rejection` without ICL: same as above, but every attempt uses the
#          same prompt"
# Context: Part 3 / Scheme behavior when num_solutions > 1.
# ---------------------------------------------------------------------------
def test_rejection_without_icl_repeats_the_same_prompt(run_tool, write_config,
                                                       write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=3,
            generation={"scheme": "rejection", "temperature": 0.7,
                        "max_attempts": 9}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests
    assert res.returncode == 0, res
    assert len(sent) == 3
    assert all(r["messages"] == sent[0]["messages"] for r in sent)
    row = res.rows[0]
    assert len(row["output"]) == 3
    assert all(o["icl_setup"] is None for o in row["output"])


# ---------------------------------------------------------------------------
# Phrase: "if `max_attempts` is omitted for rejection, default it to
#          `3 * num_solutions`"
# Context: Part 3 / Multiple Solutions.
# ---------------------------------------------------------------------------
def test_max_attempts_defaults_to_three_times_num_solutions(run_tool,
                                                            write_config,
                                                            write_input):
    with MockAPI(always("#### 0")) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=2,
            generation={"scheme": "rejection", "temperature": 0.7,
                        "max_attempts": None, "n": 1}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 6
    assert res.rows[0]["result"] == {"passed": 0, "failed": 6, "attempts": 6}


# Context: same phrase - a configured `max_attempts` caps the attempts.
def test_configured_max_attempts_caps_rejection(run_tool, write_config,
                                                write_input):
    with MockAPI(always("#### 0")) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=4,
            generation={"scheme": "rejection", "temperature": 0.7,
                        "max_attempts": 5}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 5
    assert res.rows[0]["result"]["attempts"] == 5


# ---------------------------------------------------------------------------
# Phrase: "legacy compatibility: when `num_solutions == 1` and no ICL is
#          configured, keep the Part 1 rejection behavior (`generation.n`
#          logical attempts) and do not apply `max_attempts`"
# Context: Part 3 / Multiple Solutions.
# ---------------------------------------------------------------------------
def test_legacy_rejection_uses_n_and_ignores_max_attempts(run_tool,
                                                          write_config,
                                                          write_input):
    with MockAPI(always("#### 0")) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.7, "n": 4,
                        "max_attempts": 12}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 4
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"] == {"passed": False, "extracted_answer": None,
                             "attempts": 4}


# Context: same phrase - the legacy path still stops at the first pass.
def test_legacy_rejection_stops_at_first_pass(run_tool, write_config,
                                              write_input):
    responder = sequence(["#### 1", "#### 42", "#### 42"])
    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=1,
            generation={"scheme": "rejection", "temperature": 0.7, "n": 5}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 2
    assert res.rows[0]["output"] == {"solution": "#### 42"}


# ---------------------------------------------------------------------------
# Phrase: "`max_attempts` applies to rejection sampling in this part"
# Context: Part 3 / Multiple Solutions - it is a rejection-only cap; a sample
# run makes exactly `num_solutions` requests regardless.
# ---------------------------------------------------------------------------
def test_max_attempts_does_not_limit_sample(run_tool, write_config,
                                            write_input):
    with MockAPI(always("#### 0")) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=4,
            generation={"scheme": "sample", "temperature": 0.7,
                        "max_attempts": 2}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 4


# ---------------------------------------------------------------------------
# Phrase: "`num_solutions` may be set in `defaults` or per task"
# Context: Part 3 / Multiple Solutions.
# ---------------------------------------------------------------------------
def test_num_solutions_from_defaults_and_per_task(run_tool, write_config,
                                                  write_input, workdir):
    import copy

    from conftest import GSM8K_TASK, multi_config

    task_a = copy.deepcopy(GSM8K_TASK)
    task_a["generation"] = {"scheme": "sample", "temperature": 0.7}
    task_b = copy.deepcopy(task_a)
    task_b["num_solutions"] = 3
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(multi_config(
            api.url, {"a": task_a, "b": task_b},
            defaults={"num_solutions": 2}))
        data_a = write_input([ROW], name="a.jsonl")
        data_b = write_input([ROW], name="b.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"a={data_a}", f"b={data_b}"], output=out)
    assert res.returncode == 0, res
    assert len(res.rows_for("a")[0]["output"]) == 2
    assert len(res.rows_for("b")[0]["output"]) == 3


# Context: same phrase - `num_solutions` must be a positive integer.
def test_invalid_num_solutions_is_an_error(run_tool, write_config,
                                           write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(api.url, num_solutions=0))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0
