"""Checkpoint 4: `agentic` with ICL and `num_solutions` (checkpoint 3's list
output format, one item per completed loop)."""

from fake_api import FakeAPI, agentic, calls, final


ICL = {"setups": [{"name": "few_shot", "examples": [
    {"input": {"question": "ex"}, "output": "ans"}]}]}

TWO_SETUPS = {"setups": [
    {"name": "setup_a", "examples": [{"input": {"question": "a"},
                                      "output": "A"}]},
    {"name": "setup_b", "examples": [{"input": {"question": "b"},
                                      "output": "B"}]}],
    "strategy": "round_robin"}


# "`agentic` also works with ICL and `num_solutions`; each solution is an
#  independent loop"
# "if `num_solutions: 2` and both loops produce a final answer on their first
#  API request ... `result.passed` is `2`, `result.failed` is `0`, and
#  `result.attempts` is `2`"
def test_num_solutions_two_independent_loops(run_agentic):
    with FakeAPI(agentic([final("142")])) as server:
        res = run_agentic(server, task={"num_solutions": 2},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    row = res.rows[0]
    assert row["output"] == [{"answer": "142", "icl_setup": None},
                             {"answer": "142", "icl_setup": None}]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert server.call_count == 2


# "`meta` is a list with two entries, one aggregated agentic metadata object
#  per loop"
def test_meta_is_one_aggregated_object_per_loop(run_agentic):
    with FakeAPI(agentic([final("142")])) as server:
        res = run_agentic(server, task={"num_solutions": 2},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    metas = res.rows[0]["meta"]
    assert isinstance(metas, list) and len(metas) == 2
    for meta in metas:
        assert meta["total_prompt_tokens"] == 45
        assert meta["total_completion_tokens"] == 120
        assert meta["total_tokens"] == 165
        assert len(meta["iterations_detail"]) == 1
        assert meta["finish_reason"] == "stop"


# "per-loop agentic metadata lives in each `meta` entry: keep checkpoint 3's
#  `icl_setup` / `evaluation_passed` fields and also record that loop's
#  aggregated `total_prompt_tokens`, `total_completion_tokens`,
#  `total_tokens`, `latency_ms`, `finish_reason`, and `iterations_detail`"
def test_meta_entry_keys_in_the_list_format(run_agentic):
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, task={"icl": ICL},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    meta = res.rows[0]["meta"][0]
    assert set(meta) == {"icl_setup", "evaluation_passed",
                         "total_prompt_tokens", "total_completion_tokens",
                         "total_tokens", "latency_ms", "finish_reason",
                         "iterations_detail"}
    assert meta["icl_setup"] == "few_shot"
    assert meta["evaluation_passed"] is True
    assert len(meta["iterations_detail"]) == 2
    assert meta["total_prompt_tokens"] == 90


# "when ICL is configured or `num_solutions > 1`, keep the checkpoint 3 list
#  output format"  -- ICL alone is enough, even with num_solutions == 1.
def test_icl_alone_switches_to_the_list_format(run_agentic):
    with FakeAPI(agentic([final("142")])) as server:
        res = run_agentic(server, task={"icl": ICL},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    row = res.rows[0]
    assert row["output"] == [{"answer": "142", "icl_setup": "few_shot"}]
    assert row["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert isinstance(row["meta"], list) and len(row["meta"]) == 1


# "each emitted output item represents one completed agentic loop"
def test_a_loop_that_hits_max_iterations_emits_no_output_item(run_agentic):
    # Loop 1 and 2 both spin on tool calls forever: no output items at all.
    with FakeAPI(agentic([calls(("lookup", {"key": "employees"}))])) as server:
        res = run_agentic(server,
                          task={"num_solutions": 2,
                                "generation": {"scheme": "agentic",
                                               "max_iterations": 2,
                                               "temperature": 0.0,
                                               "max_tokens": 512}},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    row = res.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert [m["finish_reason"] for m in row["meta"]] == ["max_iterations",
                                                         "max_iterations"]
    assert server.call_count == 4


# "in that list format, `result.attempts` is the number of loops started for
#  the row, not the number of API requests across those loops"
def test_attempts_counts_loops_not_requests(run_agentic):
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, task={"num_solutions": 3},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    assert res.rows[0]["result"]["attempts"] == 3
    assert server.call_count == 6          # 3 loops x 2 requests


# ICL setups still rotate per loop under the configured strategy.
def test_setups_rotate_across_loops(run_agentic):
    with FakeAPI(agentic([final("142")])) as server:
        res = run_agentic(server, task={"icl": TWO_SETUPS, "num_solutions": 2},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    names = sorted(item["icl_setup"] for item in res.rows[0]["output"])
    assert names == ["setup_a", "setup_b"]
    assert sorted(m["icl_setup"] for m in res.rows[0]["meta"]) == \
        ["setup_a", "setup_b"]


# "when evaluation is omitted in the checkpoint 3 list format ...
#  `result.passed` is the number of emitted outputs, `result.failed` is the
#  number of loops that produced no output, and each metadata entry sets
#  `evaluation_passed` to `null`"
def test_no_evaluation_in_the_list_format(run_agentic):
    with FakeAPI(agentic([final("142")])) as server:
        res = run_agentic(server, task={"evaluation": None,
                                        "num_solutions": 2},
                          rows=[{"question": "q"}], check=0)
    row = res.rows[0]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert [m["evaluation_passed"] for m in row["meta"]] == [None, None]


def test_no_evaluation_counts_loops_without_output_as_failed(run_agentic):
    # One loop answers, the other exhausts its iterations.
    per_row = {"answerable": [final("142")],
               "spinner": [calls(("lookup", {"key": "employees"}))]}
    with FakeAPI(agentic([final("142")], per_row=per_row)) as server:
        res = run_agentic(server,
                          task={"evaluation": None, "num_solutions": 2,
                                "generation": {"scheme": "agentic",
                                               "max_iterations": 2,
                                               "temperature": 0.0,
                                               "max_tokens": 512}},
                          rows=[{"question": "answerable"},
                                {"question": "spinner"}], check=0)
    ok, spin = res.rows
    assert ok["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert spin["output"] == []
    assert spin["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert [m["evaluation_passed"] for m in spin["meta"]] == [None, None]


# With evaluation configured, `passed` counts loops whose output passed.
def test_evaluation_passed_counts_in_the_list_format(run_agentic):
    per_row = {"good": [final("142")], "bad": [final("999")]}
    with FakeAPI(agentic([final("142")], per_row=per_row)) as server:
        res = run_agentic(server, task={"num_solutions": 2},
                          rows=[{"question": "good", "answer": "142"},
                                {"question": "bad", "answer": "142"}],
                          check=0)
    good, bad = res.rows
    assert good["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert bad["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    # A non-passing agentic loop still contributes its output item.
    assert bad["output"] == [{"answer": "999", "icl_setup": None},
                             {"answer": "999", "icl_setup": None}]
    assert [m["evaluation_passed"] for m in bad["meta"]] == [False, False]


# Per-task summary rollups still work for list-format agentic rows.
def test_summary_solution_counts(run_agentic):
    with FakeAPI(agentic([final("142")])) as server:
        res = run_agentic(server, task={"num_solutions": 2},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    task = res.summary["tasks"]["data_lookup"]
    assert task["total_solutions"] == 2
    assert task["avg_solutions_per_input"] == 2.0
    assert task["total_api_calls"] == 2
