"""Spec section: Part 3 / ICL Configuration (prompt layout and strategies)."""
from __future__ import annotations

import json

from conftest import (COT_SETUP, DIRECT_SETUP, TERSE_SETUP, base_config,
                      icl_config)
from mock_server import MockAPI, always, completion


ROW = {"question": "What is 15 + 27?", "answer": "42"}

# First assistant turn of each setup -> setup name, for identifying requests.
MARKERS = {
    COT_SETUP["examples"][0]["output"]: "chain_of_thought",
    DIRECT_SETUP["examples"][0]["output"]: "direct",
    TERSE_SETUP["examples"][0]["output"]: "terse",
}


def used_setups(api):
    """Setup name used by each recorded request, in call order."""
    names = []
    for req in api.requests:
        shots = [m["content"] for m in req["messages"]
                 if m.get("role") == "assistant"]
        names.append(MARKERS.get(shots[0]) if shots else None)
    return names


# ---------------------------------------------------------------------------
# Phrase: "ICL examples are inserted between the system message and the final
#          user message as alternating user and assistant turns"
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_examples_sit_between_system_and_final_user(run_tool, write_config,
                                                    write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP], strategy="fixed"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    roles = [m["role"] for m in sent["messages"]]
    assert roles == ["system", "user", "assistant", "user", "assistant",
                     "user"]
    assert sent["messages"][0]["content"].startswith("Solve the math problem")
    assert sent["messages"][-1]["content"] == "What is 15 + 27?"


# Context: same phrase - with no system prompt the examples still come first.
def test_examples_without_a_system_message(run_tool, write_config,
                                           write_input):
    cfg_dict = icl_config(api_url="", setups=[TERSE_SETUP], strategy="fixed")
    with MockAPI(always("#### 42")) as api:
        cfg_dict["task"]["api_url"] = api.url
        cfg_dict["task"]["prompt"].pop("system")
        cfg = write_config(cfg_dict)
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert [m["role"] for m in sent["messages"]] == ["user", "assistant",
                                                     "user"]


# ---------------------------------------------------------------------------
# Phrase: "each example's `input` is rendered with the task's `prompt.user`
#          template"
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_example_input_is_rendered_with_the_user_template(run_tool,
                                                          write_config,
                                                          write_input):
    setup = {"name": "mc", "examples": [
        {"input": {"question": "Pick one", "a": "x", "b": "y"},
         "output": "B"}]}
    cfg_dict = base_config("", icl={"setups": [setup], "strategy": "fixed"})
    cfg_dict["task"]["prompt"]["user"] = "{question}\nA) {a}\nB) {b}"
    with MockAPI(always("B")) as api:
        cfg_dict["task"]["api_url"] = api.url
        cfg = write_config(cfg_dict)
        data = write_input([{"question": "Real?", "a": "p", "b": "q",
                             "answer": "B"}])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["messages"][1]["content"] == "Pick one\nA) x\nB) y"
    assert sent["messages"][-1]["content"] == "Real?\nA) p\nB) q"


# ---------------------------------------------------------------------------
# Phrase: "each example's `output` is inserted verbatim as the assistant
#          message"
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_example_output_is_verbatim(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP], strategy="fixed"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["messages"][2]["content"] == COT_SETUP["examples"][0]["output"]
    assert sent["messages"][4]["content"] == COT_SETUP["examples"][1]["output"]


# ---------------------------------------------------------------------------
# Phrase: "`icl.k` defaults to all examples in the selected setup"
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_k_defaults_to_all_examples(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP], strategy="fixed"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert len([m for m in sent["messages"]
                if m["role"] == "assistant"]) == 2


# ---------------------------------------------------------------------------
# Phrase: "if `k` is smaller than the number of examples in the setup, use the
#          first `k`"
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_k_smaller_than_setup_uses_the_first_k(run_tool, write_config,
                                               write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP], k=1,
                                      strategy="fixed"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    shots = [m["content"] for m in sent["messages"]
             if m["role"] == "assistant"]
    assert shots == [COT_SETUP["examples"][0]["output"]]


# Context: same phrase (AMBIGUITIES T43) - a `k` above the setup size uses all
# available examples rather than failing.
def test_k_larger_than_setup_uses_all_examples(run_tool, write_config,
                                               write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [TERSE_SETUP], k=9,
                                      strategy="fixed"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert len([m for m in sent["messages"]
                if m["role"] == "assistant"]) == 1


# ---------------------------------------------------------------------------
# Phrase: "`fixed`: always use the first setup"
# Context: Part 3 / Strategy behavior.
# ---------------------------------------------------------------------------
def test_fixed_always_uses_the_first_setup(run_tool, write_config,
                                           write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [DIRECT_SETUP, COT_SETUP, TERSE_SETUP],
            strategy="fixed",
            generation={"scheme": "sample", "temperature": 0.7},
            num_solutions=4))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        names = used_setups(api)
    assert res.returncode == 0, res
    assert names == ["direct"] * 4
    assert [o["icl_setup"] for o in res.rows[0]["output"]] == ["direct"] * 4


# Context: same block (AMBIGUITIES T42) - `strategy` defaults to `fixed`.
def test_strategy_defaults_to_fixed(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [DIRECT_SETUP, COT_SETUP],
            generation={"scheme": "sample", "temperature": 0.7},
            num_solutions=3))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        names = used_setups(api)
    assert res.returncode == 0, res
    assert names == ["direct"] * 3


# ---------------------------------------------------------------------------
# Phrase: "`round_robin`: cycle through setups in order across attempts"
# Context: Part 3 / Strategy behavior, and the "Round-robin order with setups
# [A, B, C]" example: attempts use A, B, C, A, B.
# ---------------------------------------------------------------------------
def test_round_robin_cycles_a_b_c_a_b(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP, DIRECT_SETUP, TERSE_SETUP],
            strategy="round_robin",
            generation={"scheme": "sample", "temperature": 0.7},
            num_solutions=5))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        names = used_setups(api)
    assert res.returncode == 0, res
    assert names == ["chain_of_thought", "direct", "terse",
                     "chain_of_thought", "direct"]
    assert [o["icl_setup"] for o in res.rows[0]["output"]] == names


# Context: same phrase (AMBIGUITIES T44) - the cycle restarts for every input
# row, so each row's first attempt uses the first setup.
def test_round_robin_restarts_per_row(run_tool, write_config, write_input):
    def responder(req, i):
        return 200, completion("#### 42")

    with MockAPI(responder) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP, DIRECT_SETUP],
            strategy="round_robin",
            generation={"scheme": "sample", "temperature": 0.7},
            num_solutions=2))
        data = write_input([ROW, dict(ROW, question="Another?")])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    for row in res.rows:
        assert [o["icl_setup"] for o in row["output"]] == ["chain_of_thought",
                                                           "direct"]


# ---------------------------------------------------------------------------
# Phrase: "`random`: choose a setup independently for each attempt"
# Context: Part 3 / Strategy behavior.
# ---------------------------------------------------------------------------
def test_random_picks_declared_setups_and_varies(run_tool, write_config,
                                                 write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP, DIRECT_SETUP], strategy="random",
            generation={"scheme": "sample", "temperature": 0.7},
            num_solutions=30))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        names = used_setups(api)
    assert res.returncode == 0, res
    assert len(names) == 30
    assert set(names) <= {"chain_of_thought", "direct"}
    # Independent draws over 30 attempts: both setups appear (p(fail) ~ 2e-9).
    assert len(set(names)) == 2


# Context: same phrase - with a single setup, "random" still uses that setup.
def test_random_with_one_setup(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP], strategy="random",
            generation={"scheme": "sample", "temperature": 0.7},
            num_solutions=3))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert [o["icl_setup"] for o in res.rows[0]["output"]] == \
        ["chain_of_thought"] * 3
