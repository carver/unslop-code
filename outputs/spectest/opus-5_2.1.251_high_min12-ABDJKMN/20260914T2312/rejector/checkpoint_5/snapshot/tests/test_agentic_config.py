"""Checkpoint 4 configuration: the `agentic` scheme, `tools`, and their
validation.  Each test names the spec phrase it pins down."""

import json

import pytest

from conftest import agentic_config
from fake_api import FakeAPI, always, final, calls, agentic


# "Extend the pipeline with an `agentic` generation mode."
#   scheme: "agentic"
def test_agentic_scheme_runs(run_agentic):
    # An agentic task config from the spec example must be accepted and run.
    with FakeAPI(agentic([final("The answer is 142.")])) as server:
        res = run_agentic(server, rows=[{"question": "how many?",
                                         "answer": "142"}], check=0)
    assert res.rows[0]["output"] == {"answer": "The answer is 142."}


# "generation: scheme: "agentic", max_iterations: 10, temperature: 0.0"
#   temperature 0.0 is legal for agentic (unlike sample/rejection).
def test_agentic_allows_zero_temperature(run_agentic):
    with FakeAPI(agentic([final("42")])) as server:
        res = run_agentic(server, task={"generation": {
            "scheme": "agentic", "max_iterations": 10, "temperature": 0.0,
            "max_tokens": 512}}, rows=[{"question": "q", "answer": "42"}],
            check=0)
    assert res.summary["total"] == 1


def test_agentic_temperature_is_sent_verbatim(run_agentic):
    # An agentic task is not forced to temperature 0 the way `greedy` is.
    with FakeAPI(agentic([final("42")])) as server:
        run_agentic(server, task={"generation": {
            "scheme": "agentic", "temperature": 0.7, "max_tokens": 512}},
            rows=[{"question": "q", "answer": "42"}], check=0)
        assert server.requests[0].body["temperature"] == 0.7


# "--scheme <...>" must accept agentic as a CLI override too.
def test_scheme_cli_override_to_agentic(run_task):
    with FakeAPI(agentic([final("42")])) as server:
        task = agentic_config(generation={"max_iterations": 4,
                                          "max_tokens": 512,
                                          "temperature": 0.0})
        res = run_task(server=server, task=task,
                       rows=[{"question": "q", "answer": "42"}],
                       extra=["--scheme", "agentic"], check=0)
    assert res.rows[0]["result"]["iterations"] == 1


# "tools:" is a list of tool definitions with name/description/parameters.
def test_tool_requires_a_name(run_agentic):
    bad = {"description": "d", "parameters": {"type": "object"},
           "handler": {"type": "echo"}}
    with FakeAPI(always("x")) as server:
        res = run_agentic(server, task={"tools": [bad]}, check=1)
    assert "error" in res.stderr.lower()
    assert not res.output_exists


def test_tools_must_be_a_list(run_agentic):
    with FakeAPI(always("x")) as server:
        res = run_agentic(server, task={"tools": {"name": "lookup"}}, check=1)
    assert "error" in res.stderr.lower()


def test_tool_handler_type_must_be_known(run_agentic):
    bad = {"name": "t", "description": "d", "parameters": {"type": "object"},
           "handler": {"type": "sorcery"}}
    with FakeAPI(always("x")) as server:
        res = run_agentic(server, task={"tools": [bad]}, check=1)
    assert "sorcery" in res.stderr


def test_script_handler_requires_command_and_arg_field(run_agentic):
    bad = {"name": "run", "description": "d", "parameters": {"type": "object"},
           "handler": {"type": "script", "arg_field": "code"}}
    with FakeAPI(always("x")) as server:
        res = run_agentic(server, task={"tools": [bad]}, check=1)
    assert "command" in res.stderr


# "max_iterations" must be a positive integer.
@pytest.mark.parametrize("value", [0, -1, "many"])
def test_max_iterations_must_be_a_positive_integer(run_agentic, value):
    with FakeAPI(always("x")) as server:
        res = run_agentic(server,
                          task={"generation": {"scheme": "agentic",
                                               "max_iterations": value,
                                               "max_tokens": 512}}, check=1)
    assert "max_iterations" in res.stderr


def test_max_iterations_defaults_when_absent(run_agentic):
    # Omitted `max_iterations` must not be an error; the loop still ends on
    # a final text response.
    with FakeAPI(agentic([calls(("lookup", {"key": "employees"})),
                          final("142")])) as server:
        res = run_agentic(server,
                          task={"generation": {"scheme": "agentic",
                                               "temperature": 0.0,
                                               "max_tokens": 512}},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    assert res.rows[0]["result"]["iterations"] == 2


# An agentic task with no evaluation configured is legal (evaluation is only
# mandatory for `rejection`).
def test_agentic_without_evaluation(run_agentic):
    with FakeAPI(agentic([final("142")])) as server:
        res = run_agentic(server, task={"evaluation": None},
                          rows=[{"question": "q"}], check=0)
    assert res.rows[0]["result"]["passed"] is None


# Tools may be declared in a multi-task config, per task and via `defaults`.
def test_tools_from_multi_task_defaults(run_multi):
    tools = [json.loads(json.dumps(agentic_config()["tools"][0]))]
    with FakeAPI(agentic([calls(("lookup", {"key": "employees"})),
                          final("142")])) as server:
        res = run_multi(
            server,
            defaults={"tools": tools,
                      "generation": {"scheme": "agentic", "max_tokens": 512}},
            replace_tasks=True,
            tasks={"lookup_task": {
                "prompt": {"system": "s", "user": "{question}"},
                "output_field": "answer",
                "evaluation": {"type": "exact_match", "answer_field": "answer",
                               "extract": "last_number"}}},
            inputs={"lookup_task": [{"question": "q", "answer": "142"}]},
            check=0)
    rows = res.task_rows("lookup_task")
    assert rows[0]["result"]["iterations"] == 2
    assert rows[0]["result"]["tool_calls"][0]["tool"] == "lookup"
