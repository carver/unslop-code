"""End-to-end tests for the agentic scheme: tool calls, loops, and their output."""

import time

import httpx
import yaml

LOOKUP = {
    "name": "lookup",
    "description": "Look up a value in the database by key",
    "parameters": {
        "type": "object",
        "properties": {"key": {"type": "string", "description": "The database key to look up"}},
        "required": ["key"],
    },
    "handler": {
        "type": "static_map",
        "mapping": {"revenue_q1": "1250000", "revenue_q2": "1480000", "employees": "142"},
        "default": "KEY_NOT_FOUND",
    },
}
CALCULATE = {
    "name": "calculate",
    "description": "Evaluate a mathematical expression",
    "parameters": {
        "type": "object",
        "properties": {"expression": {"type": "string", "description": "The math expression"}},
        "required": ["expression"],
    },
    "handler": {"type": "echo"},
}
RUN_PYTHON = {
    "name": "run_python",
    "description": "Run a Python snippet and return what it prints",
    "parameters": {
        "type": "object",
        "properties": {"code": {"type": "string", "description": "The Python source to run"}},
        "required": ["code"],
    },
    "handler": {"type": "script", "command": "python3 -c", "arg_field": "code"},
}

EVALUATION = {"type": "exact_match", "answer_field": "answer", "extract": "last_number"}


def config(url, *, tools=(LOOKUP,), evaluation=EVALUATION, generation=None, **task):
    """Build a single agentic task pointed at the mock server."""
    document = {
        "task": {
            "name": "data_lookup",
            "api_url": url,
            "model": "mock-model",
            "rpm": 600,
            "prompt": {"system": "Use the tools to answer.", "user": "{question}"},
            "generation": {"scheme": "agentic", "temperature": 0.0, "max_tokens": 64, **(generation or {})},
            "output_field": "answer",
            "tools": list(tools),
            **task,
        }
    }
    if evaluation is not None:
        document["task"]["evaluation"] = evaluation
    return yaml.safe_dump(document)


def asking(tool, args, question="What is the answer?", answer="8"):
    """An input row whose question makes the mock server request one tool call."""
    marker = f'CALL {tool} {{"{args[0]}": "{args[1]}"}}'
    return {"question": f"{marker} {question}", "answer": answer}


def test_tool_call_then_final_answer(mock_server, run_cli):
    server = mock_server()
    rows = [asking("lookup", ("key", "employees"), "How many employees?", "142")]

    completed, summary, results = run_cli(config(server.url), rows)

    assert completed.returncode == 0, completed.stderr
    result = results[0]["result"]
    assert results[0]["output"]["answer"].endswith("#### 142")
    assert result["passed"] is True
    assert result["extracted_answer"] == "142"
    assert result["attempts"] == 1
    assert result["iterations"] == 2
    assert result["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]
    assert summary["total_api_calls"] == 2


def test_meta_aggregates_every_iteration(mock_server, run_cli):
    server = mock_server()
    rows = [asking("lookup", ("key", "employees"), "How many employees?", "142")]

    _, _, results = run_cli(config(server.url), rows)

    meta = results[0]["meta"]
    detail = meta["iterations_detail"]
    assert len(detail) == 2
    assert [step["finish_reason"] for step in detail] == ["tool_calls", "stop"]
    assert meta["finish_reason"] == "stop"
    assert meta["total_prompt_tokens"] == sum(step["prompt_tokens"] for step in detail)
    assert meta["total_completion_tokens"] == sum(step["completion_tokens"] for step in detail)
    assert meta["total_tokens"] == sum(step["total_tokens"] for step in detail)
    assert meta["latency_ms"] >= max(step["latency_ms"] for step in detail)


def test_every_tool_call_of_one_response_runs(mock_server, run_cli):
    server = mock_server()
    question = 'CALL lookup {"key": "revenue_q1"} CALL lookup {"key": "revenue_q2"} Total revenue?'
    rows = [{"question": question, "answer": "1480000"}]

    _, _, results = run_cli(config(server.url), rows)

    assert results[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"}, "result": "1250000"},
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"}, "result": "1480000"},
    ]
    assert results[0]["result"]["iterations"] == 2


def test_max_iterations_gives_up(mock_server, run_cli):
    server = mock_server("--always-call-tools")
    rows = [asking("lookup", ("key", "employees"))]

    _, summary, results = run_cli(config(server.url, generation={"max_iterations": 3}), rows)

    assert results[0]["output"] is None
    assert results[0]["result"]["passed"] is False
    assert results[0]["result"]["iterations"] == 3
    assert len(results[0]["result"]["tool_calls"]) == 3
    assert results[0]["meta"]["finish_reason"] == "max_iterations"
    assert len(results[0]["meta"]["iterations_detail"]) == 3
    assert summary["failed"] == 1


def test_static_map_falls_back_to_its_default(mock_server, run_cli):
    server = mock_server()
    rows = [asking("lookup", ("key", "headcount"))]

    _, _, results = run_cli(config(server.url), rows)

    assert results[0]["result"]["tool_calls"][0]["result"] == "KEY_NOT_FOUND"


def test_echo_handler_returns_the_arguments(mock_server, run_cli):
    server = mock_server()
    rows = [asking("calculate", ("expression", "40 + 2"))]

    _, _, results = run_cli(config(server.url, tools=(LOOKUP, CALCULATE)), rows)

    assert results[0]["result"]["tool_calls"][0]["result"] == '{"expression": "40 + 2"}'


def test_script_handler_returns_stdout(mock_server, run_cli):
    server = mock_server()
    rows = [asking("run_python", ("code", "print(6 * 7)"), answer="42")]

    _, _, results = run_cli(config(server.url, tools=(RUN_PYTHON,)), rows)

    assert results[0]["result"]["tool_calls"][0]["result"] == "42"
    assert results[0]["result"]["passed"] is True


def test_script_handler_reports_failures(mock_server, run_cli):
    server = mock_server()
    rows = [asking("run_python", ("code", "raise SystemExit('boom')"))]

    _, _, results = run_cli(config(server.url, tools=(RUN_PYTHON,)), rows)

    assert results[0]["result"]["tool_calls"][0]["result"].startswith("ERROR: ")
    assert "boom" in results[0]["result"]["tool_calls"][0]["result"]


def test_unknown_tool_is_reported_to_the_model(mock_server, run_cli):
    server = mock_server()
    rows = [asking("missing_tool", ("key", "employees"))]

    _, _, results = run_cli(config(server.url), rows)

    assert results[0]["result"]["tool_calls"][0]["result"] == "ERROR: unknown tool 'missing_tool'"


def test_without_evaluation_passed_is_null(mock_server, run_cli):
    server = mock_server()
    rows = [asking("lookup", ("key", "employees"))]

    _, _, results = run_cli(config(server.url, evaluation=None), rows)

    assert results[0]["result"]["passed"] is None
    assert results[0]["output"] is not None


def test_without_evaluation_max_iterations_still_fails(mock_server, run_cli):
    server = mock_server("--always-call-tools")
    rows = [asking("lookup", ("key", "employees"))]

    _, _, results = run_cli(
        config(server.url, evaluation=None, generation={"max_iterations": 2}), rows
    )

    assert results[0]["result"]["passed"] is False
    assert results[0]["output"] is None


def test_num_solutions_writes_one_entry_per_loop(mock_server, run_cli):
    server = mock_server()
    rows = [asking("lookup", ("key", "employees"), "How many employees?", "142")]

    _, _, results = run_cli(config(server.url, num_solutions=2), rows)

    assert results[0]["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert len(results[0]["output"]) == 2
    assert all(item["icl_setup"] is None for item in results[0]["output"])
    metas = results[0]["meta"]
    assert len(metas) == 2
    for meta in metas:
        assert meta["evaluation_passed"] is True
        assert meta["finish_reason"] == "stop"
        assert len(meta["iterations_detail"]) == 2


def test_icl_setups_drive_each_loop(mock_server, run_cli):
    server = mock_server()
    icl = {
        "setups": [
            {"name": "direct", "examples": [{"input": {"question": "2+2?"}, "output": "#### 4"}]},
            {"name": "verbose", "examples": [{"input": {"question": "2+2?"}, "output": "2+2 is 4\n#### 4"}]},
        ],
        "strategy": "round_robin",
    }
    rows = [asking("lookup", ("key", "employees"), "How many employees?", "142")]

    _, _, results = run_cli(config(server.url, icl=icl, num_solutions=2), rows)

    assert [item["icl_setup"] for item in results[0]["output"]] == ["direct", "verbose"]
    assert [meta["icl_setup"] for meta in results[0]["meta"]] == ["direct", "verbose"]
    # system + one user/assistant example turn + the question, then the tool call and its result
    assert "turns=6" in results[0]["output"][0]["answer"]


def test_loops_of_different_rows_overlap(mock_server, run_cli):
    """Three rows, each spending two requests, must not serialize into six round trips."""
    server = mock_server("--latency", "0.25", "--capacity", "8")
    rows = [asking("lookup", ("key", "employees"), f"Question {index}?", "142") for index in range(3)]

    started = time.monotonic()
    completed, summary, results = run_cli(config(server.url), rows)
    elapsed = time.monotonic() - started

    assert completed.returncode == 0, completed.stderr
    assert summary["total_api_calls"] == 6
    assert all(result["result"]["iterations"] == 2 for result in results)
    # Two overlapping rounds of 0.25s, well short of six serial ones.
    assert elapsed < 1.5


def test_a_loop_holds_one_concurrency_slot_for_its_whole_life(mock_server, run_cli):
    """With ``max_concurrent: 1`` a second row may not start between the first row's requests."""
    server = mock_server("--latency", "0.1", "--capacity", "8")
    rows = [asking("lookup", ("key", "employees"), f"Question {index}?", "142") for index in range(3)]
    limits = {"rate_limits": {"rpm": 600, "max_concurrent": 1}}

    completed, summary, results = run_cli(config(server.url, **limits), rows)

    assert completed.returncode == 0, completed.stderr
    assert summary["total_api_calls"] == 6
    assert all(result["result"]["iterations"] == 2 for result in results)
    assert httpx.get(server.url).json()["peak"] == 1


def test_unknown_handler_type_is_a_config_error(mock_server, run_cli):
    server = mock_server()
    broken = {**LOOKUP, "handler": {"type": "http"}}

    completed, _, _ = run_cli(config(server.url, tools=(broken,)), [asking("lookup", ("key", "a"))])

    assert completed.returncode == 1
    assert "handler.type must be one of" in completed.stderr


def test_static_map_needs_a_required_parameter(mock_server, run_cli):
    server = mock_server()
    broken = {**LOOKUP, "parameters": {"type": "object", "properties": {}}}

    completed, _, _ = run_cli(config(server.url, tools=(broken,)), [asking("lookup", ("key", "a"))])

    assert completed.returncode == 1
    assert "required parameter" in completed.stderr


def test_max_iterations_must_be_positive(mock_server, run_cli):
    server = mock_server()

    completed, _, _ = run_cli(
        config(server.url, generation={"max_iterations": 0}), [asking("lookup", ("key", "a"))]
    )

    assert completed.returncode == 1
    assert "max_iterations" in completed.stderr
