"""Spec section: Part 4 / Agentic Generation (task configuration)."""
from __future__ import annotations

import copy

from conftest import (AGENTIC_ROW, CALC_TOOL, LOOKUP_TOOL, agentic_config,
                      agentic_replies, base_config)
from mock_server import MockAPI, always


FINAL = "The total revenue for Q1 and Q2 is 2730000."


# ---------------------------------------------------------------------------
# Phrase: "Extend the pipeline with an `agentic` generation mode"
# Context: Part 4 intro; `generation.scheme: "agentic"` in the task example.
# ---------------------------------------------------------------------------
def test_agentic_scheme_is_accepted(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL, CALC_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["output"] == {"answer": FINAL}


# Context: same phrase - `--scheme agentic` is a valid CLI choice too.
def test_agentic_scheme_via_cli_flag(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(base_config(api.url, tools=[LOOKUP_TOOL],
                                       output_field="answer"))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data, extra=["--scheme", "agentic"])
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["iterations"] == 1


# ---------------------------------------------------------------------------
# Phrase: "generation: scheme: 'agentic' / max_iterations: 10 /
#          temperature: 0.0"
# Context: Part 4 / Agentic Generation task example.  `agentic` keeps
#          temperature 0.0 (AMBIGUITIES T63).
# ---------------------------------------------------------------------------
def test_agentic_allows_temperature_zero(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        temps = [r["temperature"] for r in api.requests]
    assert res.returncode == 0, res
    assert temps == [0.0]


# Context: same phrase - a configured non-zero temperature is passed through.
def test_agentic_passes_configured_temperature(run_tool, write_config,
                                               write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(
            api.url, [LOOKUP_TOOL], generation={"temperature": 0.7}))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        temps = [r["temperature"] for r in api.requests]
    assert res.returncode == 0, res
    assert temps == [0.7]


# Context: `max_iterations` must be a positive integer.
def test_max_iterations_must_be_positive(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(
            api.url, [LOOKUP_TOOL], generation={"max_iterations": 0}))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0
    assert "max_iterations" in res.stderr


# ---------------------------------------------------------------------------
# Phrase: "tools: - name / description / parameters / handler"
# Context: Part 4 / Agentic Generation task example - the tool list is a
#          task-level key next to `generation`.
# ---------------------------------------------------------------------------
def test_tool_needs_a_name(run_tool, write_config, write_input):
    tool = copy.deepcopy(LOOKUP_TOOL)
    tool.pop("name")
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [tool]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


def test_tool_needs_a_known_handler_type(run_tool, write_config, write_input):
    tool = copy.deepcopy(LOOKUP_TOOL)
    tool["handler"] = {"type": "sorcery"}
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [tool]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0
    assert "handler" in res.stderr


def test_tools_must_be_a_list(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(api.url, {"lookup": LOOKUP_TOOL}))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 1, res


# ---------------------------------------------------------------------------
# Phrase: "In chat mode, include the task's tool definitions in the request
#          body."
# Context: Part 4 / Agentic loop step 2.  Tools belong to agentic tasks only
#          (AMBIGUITIES T69, T70).
# ---------------------------------------------------------------------------
def test_tools_are_not_sent_for_non_agentic_schemes(run_tool, write_config,
                                                    write_input):
    with MockAPI(always("#### 2730000")) as api:
        cfg = write_config(base_config(api.url, tools=[LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        bodies = list(api.requests)
    assert res.returncode == 0, res
    assert "tools" not in bodies[0]


def test_agentic_without_tools_still_runs(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(api.url, None))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        bodies = list(api.requests)
    assert res.returncode == 0, res
    assert "tools" not in bodies[0]
    assert res.rows[0]["output"] == {"answer": FINAL}


# ---------------------------------------------------------------------------
# Phrase: "Existing behavior from earlier parts is unchanged unless stated
#          here."
# Context: Part 4 intro - `agentic` is additive; other schemes keep working.
# ---------------------------------------------------------------------------
def test_greedy_still_works_unchanged(run_tool, write_config, write_input):
    with MockAPI(always("#### 2730000")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["result"]["passed"] is True
    assert "iterations" not in row["result"]
