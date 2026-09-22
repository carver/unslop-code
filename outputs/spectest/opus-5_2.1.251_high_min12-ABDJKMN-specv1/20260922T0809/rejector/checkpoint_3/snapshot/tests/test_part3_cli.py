"""Spec section: Part 3 / Multiple Solutions (new CLI flags)."""
from __future__ import annotations

import copy

from conftest import (COT_SETUP, DIRECT_SETUP, GSM8K_TASK, TERSE_SETUP,
                      base_config, icl_config, multi_config)
from mock_server import MockAPI, always


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
# Phrase: "New flags: `--num-solutions <int>`"
# Context: Part 3 / Multiple Solutions.
# ---------------------------------------------------------------------------
def test_num_solutions_flag(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(
            api.url, generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--num-solutions", "3"])
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 3
    assert len(res.rows[0]["output"]) == 3


# ---------------------------------------------------------------------------
# Phrase: "CLI flags override config values"
# Context: Part 3 / Multiple Solutions.
# ---------------------------------------------------------------------------
def test_num_solutions_flag_overrides_config(run_tool, write_config,
                                             write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=5,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--num-solutions", "2"])
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 2


# ---------------------------------------------------------------------------
# Phrase: "New flags: `--icl-strategy <fixed|random|round_robin>`"
# Context: Part 3 / Multiple Solutions.
# ---------------------------------------------------------------------------
def test_icl_strategy_flag_overrides_config(run_tool, write_config,
                                            write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP, DIRECT_SETUP], strategy="fixed",
            num_solutions=2,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--icl-strategy", "round_robin"])
        names = used_setups(api)
    assert res.returncode == 0, res
    assert names == ["chain_of_thought", "direct"]


# Context: same phrase - only the three documented strategies are accepted.
def test_icl_strategy_flag_rejects_unknown_value(run_tool, write_config,
                                                 write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP]))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--icl-strategy", "sorted"])
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


# ---------------------------------------------------------------------------
# Phrase: "New flags: `--icl-k <int>`"
# Context: Part 3 / Multiple Solutions.
# ---------------------------------------------------------------------------
def test_icl_k_flag_overrides_config(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP], k=2))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--icl-k", "1"])
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert len([m for m in sent["messages"]
                if m["role"] == "assistant"]) == 1


# Context: same phrase - a non-integer `--icl-k` is a usage error.
def test_icl_k_flag_requires_an_integer(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP]))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--icl-k", "two"])
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


# Context: same phrase - `--num-solutions` must be a positive integer.
def test_num_solutions_flag_rejects_zero(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--num-solutions", "0"])
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


# ---------------------------------------------------------------------------
# Phrase: "CLI flags override config values" - in a multi-task config the
#         flags apply to every selected task (Part 2 / T35 scope rule).
# Context: Part 3 / Multiple Solutions.
# ---------------------------------------------------------------------------
def test_flags_apply_to_every_selected_task(run_tool, write_config,
                                            write_input, workdir):
    task_a = copy.deepcopy(GSM8K_TASK)
    task_a["generation"] = {"scheme": "sample", "temperature": 0.7}
    task_b = copy.deepcopy(task_a)
    task_b["num_solutions"] = 4
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(multi_config(api.url, {"a": task_a, "b": task_b}))
        data_a = write_input([ROW], name="a.jsonl")
        data_b = write_input([ROW], name="b.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"a={data_a}", f"b={data_b}"], output=out,
                       extra=["--num-solutions", "2"])
    assert res.returncode == 0, res
    assert len(res.rows_for("a")[0]["output"]) == 2
    assert len(res.rows_for("b")[0]["output"]) == 2


# ---------------------------------------------------------------------------
# Phrase: "New flags" (AMBIGUITIES T56) - `--icl-k` / `--icl-strategy` on a
#         task without ICL are accepted and do nothing.
# Context: Part 3 / Multiple Solutions.
# ---------------------------------------------------------------------------
def test_icl_flags_without_icl_config_are_harmless(run_tool, write_config,
                                                   write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([ROW])
        res = run_tool(cfg, data,
                       extra=["--icl-k", "2", "--icl-strategy", "random"])
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert res.rows[0]["output"] == {"solution": "#### 42"}
