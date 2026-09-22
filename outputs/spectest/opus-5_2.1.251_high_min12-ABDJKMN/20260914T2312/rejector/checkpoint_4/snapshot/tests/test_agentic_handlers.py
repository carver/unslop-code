"""Checkpoint 4 tool handlers: `echo`, `static_map` and `script`."""

import json

from fake_api import FakeAPI, calls, final, agentic


def tool(name="t", handler=None, required=("key",), props=("key",)):
    return {
        "name": name,
        "description": "a tool",
        "parameters": {
            "type": "object",
            "properties": {p: {"type": "string"} for p in props},
            "required": list(required),
        },
        "handler": handler or {"type": "echo"},
    }


def one_call(run_agentic, server, tool_def, name, args, rows=None):
    """Run a single-row agentic task whose first turn calls `name(args)`."""
    res = run_agentic(server, task={"tools": [tool_def]},
                      rows=rows or [{"question": "q", "answer": "0"}],
                      check=0)
    return res.rows[0]["result"]["tool_calls"]


# "echo: return the parsed tool arguments as a JSON string"
def test_echo_handler_returns_arguments_as_json(run_agentic):
    with FakeAPI(agentic([calls(("calc", {"expression": "2+2"})),
                          final("4")])) as server:
        recorded = one_call(run_agentic, server,
                            tool(name="calc", handler={"type": "echo"},
                                 required=["expression"], props=["expression"]),
                            "calc", {"expression": "2+2"})
    assert json.loads(recorded[0]["result"]) == {"expression": "2+2"}
    assert isinstance(recorded[0]["result"], str)


def test_echo_handler_keeps_every_argument(run_agentic):
    args = {"expression": "2+2", "precision": 3}
    with FakeAPI(agentic([calls(("calc", args)), final("4")])) as server:
        recorded = one_call(run_agentic, server,
                            tool(name="calc", handler={"type": "echo"},
                                 required=["expression"],
                                 props=["expression", "precision"]),
                            "calc", args)
    assert json.loads(recorded[0]["result"]) == args


# "static_map: look up the first required parameter in `mapping`"
def test_static_map_looks_up_the_first_required_parameter(run_agentic):
    handler = {"type": "static_map",
               "mapping": {"revenue_q1": "1250000", "employees": "142"},
               "default": "KEY_NOT_FOUND"}
    with FakeAPI(agentic([calls(("lookup", {"key": "revenue_q1"})),
                          final("1250000")])) as server:
        recorded = one_call(run_agentic, server,
                            tool(name="lookup", handler=handler),
                            "lookup", {"key": "revenue_q1"})
    assert recorded[0]["result"] == "1250000"


# "if absent, return `default`"
def test_static_map_returns_the_configured_default(run_agentic):
    handler = {"type": "static_map", "mapping": {"employees": "142"},
               "default": "KEY_NOT_FOUND"}
    with FakeAPI(agentic([calls(("lookup", {"key": "nope"})),
                          final("0")])) as server:
        recorded = one_call(run_agentic, server,
                            tool(name="lookup", handler=handler),
                            "lookup", {"key": "nope"})
    assert recorded[0]["result"] == "KEY_NOT_FOUND"


# "`default`, which defaults to `"NOT_FOUND"`"
def test_static_map_default_default_is_not_found(run_agentic):
    handler = {"type": "static_map", "mapping": {"employees": "142"}}
    with FakeAPI(agentic([calls(("lookup", {"key": "nope"})),
                          final("0")])) as server:
        recorded = one_call(run_agentic, server,
                            tool(name="lookup", handler=handler),
                            "lookup", {"key": "nope"})
    assert recorded[0]["result"] == "NOT_FOUND"


def test_static_map_uses_the_first_required_name_not_the_first_argument(
        run_agentic):
    # `required: ["key"]` selects the lookup argument even when the model
    # sends other arguments first.
    handler = {"type": "static_map", "mapping": {"employees": "142"}}
    args = {"scope": "hr", "key": "employees"}
    with FakeAPI(agentic([calls(("lookup", args)), final("142")])) as server:
        recorded = one_call(run_agentic, server,
                            tool(name="lookup", handler=handler,
                                 required=["key"], props=["scope", "key"]),
                            "lookup", args)
    assert recorded[0]["result"] == "142"


# "script: run `command` with the value of `arg_field` as a single
#  command-line argument, capture stdout, and return it"
def test_script_handler_returns_stdout(run_agentic):
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    args = {"code": "print(6 * 7)"}
    with FakeAPI(agentic([calls(("run", args)), final("42")])) as server:
        recorded = one_call(run_agentic, server,
                            tool(name="run", handler=handler,
                                 required=["code"], props=["code"]),
                            "run", args)
    assert recorded[0]["result"].strip() == "42"


def test_script_handler_passes_the_argument_as_one_argv_entry(run_agentic):
    # The whole `arg_field` value is one argument: spaces must not split it.
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    # `python3 -c` receives the whole program as argv[1]; a split on spaces
    # would hand it several fragments and fail.
    args = {"code": "import sys; print('hello world'); print(len(sys.argv))"}
    with FakeAPI(agentic([calls(("run", args)), final("2")])) as server:
        recorded = one_call(run_agentic, server,
                            tool(name="run", handler=handler,
                                 required=["code"], props=["code"]),
                            "run", args)
    assert recorded[0]["result"].splitlines() == ["hello world", "1"]


# "on timeout or non-zero exit, return `"ERROR: <stderr or timeout message>"`"
def test_script_handler_reports_a_non_zero_exit(run_agentic):
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    args = {"code": "import sys; sys.stderr.write('bad thing'); sys.exit(3)"}
    with FakeAPI(agentic([calls(("run", args)), final("0")])) as server:
        recorded = one_call(run_agentic, server,
                            tool(name="run", handler=handler,
                                 required=["code"], props=["code"]),
                            "run", args)
    assert recorded[0]["result"].startswith("ERROR: ")
    assert "bad thing" in recorded[0]["result"]


def test_script_handler_reports_a_timeout(run_agentic):
    handler = {"type": "script", "command": "python3 -c", "arg_field": "code"}
    args = {"code": "import time; time.sleep(30)"}
    with FakeAPI(agentic([calls(("run", args)), final("0")])) as server:
        recorded = one_call(run_agentic, server,
                            tool(name="run", handler=handler,
                                 required=["code"], props=["code"]),
                            "run", args)
    assert recorded[0]["result"].startswith("ERROR: ")


# A tool result always reaches the model as a string.
def test_tool_results_are_strings_in_the_conversation(run_agentic):
    handler = {"type": "static_map", "mapping": {"employees": "142"}}
    with FakeAPI(agentic([calls(("lookup", {"key": "employees"})),
                          final("142")])) as server:
        run_agentic(server, task={"tools": [tool(name="lookup",
                                                 handler=handler)]},
                    rows=[{"question": "q", "answer": "142"}], check=0)
        second = server.requests[1]
    assert [m["content"] for m in second.tool_messages] == ["142"]
