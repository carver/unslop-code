"""Spec section: Part 4 / Agentic Generation (handler types)."""
from __future__ import annotations

import copy
import json

from conftest import (AGENTIC_ROW, CALC_TOOL, LOOKUP_TOOL, SCRIPT_TOOL,
                      agentic_config, agentic_replies)
from mock_server import MockAPI


DONE = "done"


def run_loop(run_tool, write_config, write_input, tools, calls, **cfg_kw):
    """Drive one agentic row: one tool-call round, then a final answer."""
    with MockAPI(agentic_replies([calls, DONE])) as api:
        cfg = write_config(agentic_config(api.url, tools, **cfg_kw))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
    return res


def results_of(res):
    return [c["result"] for c in res.rows[0]["result"]["tool_calls"]]


# ---------------------------------------------------------------------------
# Phrase: "`echo`: return the parsed tool arguments as a JSON string"
# Context: Part 4 / Handler types.
# ---------------------------------------------------------------------------
def test_echo_handler_returns_arguments_as_json(run_tool, write_config,
                                                write_input):
    args = {"expression": "1250000 + 1480000"}
    res = run_loop(run_tool, write_config, write_input, [CALC_TOOL],
                   [("calculate", args)])
    assert res.returncode == 0, res
    assert results_of(res) == [json.dumps(args)]


# Context: same phrase - the handler sees *parsed* arguments, so the recorded
# `args` is an object, not the raw JSON string from the API.
def test_echo_handler_records_parsed_args(run_tool, write_config, write_input):
    res = run_loop(run_tool, write_config, write_input, [CALC_TOOL],
                   [("calculate", {"expression": "2+2"})])
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["tool_calls"][0]["args"] == {"expression": "2+2"}


# ---------------------------------------------------------------------------
# Phrase: "`static_map`: look up the first required parameter in `mapping`"
# Context: Part 4 / Handler types.
# ---------------------------------------------------------------------------
def test_static_map_returns_the_mapped_value(run_tool, write_config,
                                             write_input):
    res = run_loop(run_tool, write_config, write_input, [LOOKUP_TOOL],
                   [("lookup", {"key": "employees"})])
    assert res.returncode == 0, res
    assert results_of(res) == ["142"]


# Context: same phrase - the lookup key is the first entry of
# `parameters.required`, even when other arguments are present (T75).
def test_static_map_uses_the_first_required_parameter(run_tool, write_config,
                                                      write_input):
    tool = copy.deepcopy(LOOKUP_TOOL)
    tool["parameters"]["properties"]["scope"] = {"type": "string"}
    tool["parameters"]["required"] = ["key", "scope"]
    res = run_loop(run_tool, write_config, write_input, [tool],
                   [("lookup", {"scope": "all", "key": "revenue_q1"})])
    assert res.returncode == 0, res
    assert results_of(res) == ["1250000"]


# ---------------------------------------------------------------------------
# Phrase: "if absent, return `default`"
# Context: Part 4 / Handler types (`static_map`).
# ---------------------------------------------------------------------------
def test_static_map_returns_configured_default(run_tool, write_config,
                                               write_input):
    res = run_loop(run_tool, write_config, write_input, [LOOKUP_TOOL],
                   [("lookup", {"key": "profit"})])
    assert res.returncode == 0, res
    assert results_of(res) == ["KEY_NOT_FOUND"]


# ---------------------------------------------------------------------------
# Phrase: "`default`, which defaults to `\"NOT_FOUND\"`"
# Context: Part 4 / Handler types (`static_map`).
# ---------------------------------------------------------------------------
def test_static_map_default_default_is_not_found(run_tool, write_config,
                                                 write_input):
    tool = copy.deepcopy(LOOKUP_TOOL)
    tool["handler"].pop("default")
    res = run_loop(run_tool, write_config, write_input, [tool],
                   [("lookup", {"key": "profit"})])
    assert res.returncode == 0, res
    assert results_of(res) == ["NOT_FOUND"]


# ---------------------------------------------------------------------------
# Phrase: "`script`: run `command` with the value of `arg_field` as a single
#          command-line argument, capture stdout, and return it"
# Context: Part 4 / Handler types and the script handler config example.
# ---------------------------------------------------------------------------
def test_script_handler_returns_stdout(run_tool, write_config, write_input):
    res = run_loop(run_tool, write_config, write_input, [SCRIPT_TOOL],
                   [("run_python", {"code": "print(1250000 + 1480000)"})])
    assert res.returncode == 0, res
    assert results_of(res) == ["2730000"]


# Context: same phrase - the code is passed as ONE argument, so shell
# metacharacters inside it are not interpreted by a shell.
def test_script_handler_passes_a_single_argument(run_tool, write_config,
                                                 write_input):
    code = "print('a; b > c')"
    res = run_loop(run_tool, write_config, write_input, [SCRIPT_TOOL],
                   [("run_python", {"code": code})])
    assert res.returncode == 0, res
    assert results_of(res) == ["a; b > c"]


# ---------------------------------------------------------------------------
# Phrase: "on timeout or non-zero exit, return `\"ERROR: <stderr or timeout
#          message>\"`"
# Context: Part 4 / Handler types (`script`).
# ---------------------------------------------------------------------------
def test_script_handler_reports_non_zero_exit(run_tool, write_config,
                                              write_input):
    res = run_loop(run_tool, write_config, write_input, [SCRIPT_TOOL],
                   [("run_python", {"code": "raise SystemExit('boom')"})])
    assert res.returncode == 0, res
    result = results_of(res)[0]
    assert result.startswith("ERROR:")
    assert "boom" in result


def test_script_handler_reports_timeout(run_tool, write_config, write_input):
    tool = copy.deepcopy(SCRIPT_TOOL)
    tool["handler"]["timeout"] = 1
    res = run_loop(run_tool, write_config, write_input, [tool],
                   [("run_python", {"code": "import time; time.sleep(30)"})])
    assert res.returncode == 0, res
    result = results_of(res)[0]
    assert result.startswith("ERROR:")
    assert "timeout" in result.lower() or "timed out" in result.lower()


# ---------------------------------------------------------------------------
# Phrase: "parse `function.arguments` as JSON before invoking the handler"
# Context: Part 4 / Rules.  Unparseable arguments still produce a recorded
#          call whose result is an error string (AMBIGUITIES T74).
# ---------------------------------------------------------------------------
def test_unparseable_arguments_produce_an_error_result(run_tool, write_config,
                                                       write_input):
    res = run_loop(run_tool, write_config, write_input, [LOOKUP_TOOL],
                   [("lookup", "{not json")])
    assert res.returncode == 0, res
    calls = res.rows[0]["result"]["tool_calls"]
    assert len(calls) == 1
    assert calls[0]["tool"] == "lookup"
    assert calls[0]["result"].startswith("ERROR:")


# Context: a call for a tool the task never declared (AMBIGUITIES T73).
def test_unknown_tool_name_produces_an_error_result(run_tool, write_config,
                                                    write_input):
    res = run_loop(run_tool, write_config, write_input, [LOOKUP_TOOL],
                   [("teleport", {"key": "employees"})])
    assert res.returncode == 0, res
    call = res.rows[0]["result"]["tool_calls"][0]
    assert call["tool"] == "teleport"
    assert call["result"].startswith("ERROR:")
    # the loop keeps going and the final answer is still produced
    assert res.rows[0]["output"] == {"answer": DONE}
