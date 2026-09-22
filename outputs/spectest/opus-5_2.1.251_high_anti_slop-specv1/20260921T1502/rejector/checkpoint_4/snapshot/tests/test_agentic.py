"""End to end agentic runs: the tool calling loop, its handlers and its output."""

import json
import time

import pytest
import yaml
from mock_server import start_mock_server

import rejector

TOOLS = [
    {
        "name": "lookup",
        "description": "Look up a value in the database by key",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string", "description": "The database key"}},
            "required": ["key"],
        },
        "handler": {
            "type": "static_map",
            "mapping": {"revenue_q1": "1250000", "revenue_q2": "1480000", "employees": "142"},
            "default": "KEY_NOT_FOUND",
        },
    },
    {
        "name": "calculate",
        "description": "Evaluate a mathematical expression",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
        "handler": {"type": "echo"},
    },
]

TASK = {
    "name": "data_lookup",
    "model": "gpt-4",
    "rpm": 600,
    "prompt": {
        "system": "You are a data analysis assistant. Use the provided tools.",
        "user": "{question}",
    },
    "generation": {"scheme": "agentic", "max_iterations": 10, "temperature": 0.0, "max_tokens": 512},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "answer",
    "tools": TOOLS,
}

REVENUE = {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"}


@pytest.fixture
def api():
    """Start a mock server whose responder the test installs afterwards."""
    servers = []

    def start(responder, delay=0.0, capacity=8):
        url, state, shutdown = start_mock_server(responder, delay=delay, capacity=capacity)
        servers.append(shutdown)
        return url, state

    yield start
    for shutdown in servers:
        shutdown()


def scripted(*replies):
    """Answer the n-th request of a conversation with the n-th reply, repeating the last."""

    def respond(payload, call):
        step = sum(1 for message in payload["messages"] if message["role"] == "assistant")
        return replies[min(step, len(replies) - 1)]

    return respond


def calls(*names_and_arguments):
    return [{"name": name, "arguments": arguments} for name, arguments in names_and_arguments]


def run(tmp_path, url, rows, capsys, **task):
    """Run the CLI over `rows` and return `(records, summary)`."""
    config = {**TASK, **task, "api_url": url}
    (tmp_path / "task.yaml").write_text(yaml.safe_dump({"task": config}))
    (tmp_path / "in.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert rejector.main(
        [
            "run",
            "--config", str(tmp_path / "task.yaml"),
            "--input", str(tmp_path / "in.jsonl"),
            "--output", str(tmp_path / "out.jsonl"),
        ]
    ) == 0
    records = [json.loads(line) for line in (tmp_path / "out.jsonl").read_text().splitlines()]
    return records, json.loads(capsys.readouterr().out)


def test_loop_matches_the_documented_shape(tmp_path, api, capsys):
    url, state = api(
        scripted(
            calls(("lookup", {"key": "revenue_q1"}), ("lookup", {"key": "revenue_q2"})),
            calls(("calculate", {"expression": "1250000 + 1480000"})),
            "The total revenue for Q1 and Q2 is 2730000.",
        )
    )
    records, summary = run(tmp_path, url, [REVENUE], capsys)
    record = records[0]

    assert record["input"] == REVENUE
    assert record["output"] == {"answer": "The total revenue for Q1 and Q2 is 2730000."}
    assert record["result"]["passed"] is True
    assert record["result"]["extracted_answer"] == "2730000"
    assert record["result"]["attempts"] == 1
    assert record["result"]["iterations"] == 3
    assert record["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"}, "result": "1250000"},
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"}, "result": "1480000"},
        {
            "iteration": 2,
            "tool": "calculate",
            "args": {"expression": "1250000 + 1480000"},
            "result": '{"expression": "1250000 + 1480000"}',
        },
    ]
    assert record["meta"]["total_prompt_tokens"] == 30
    assert record["meta"]["total_completion_tokens"] == 15
    assert record["meta"]["total_tokens"] == 45
    assert record["meta"]["latency_ms"] >= 0
    assert record["meta"]["finish_reason"] == "stop"
    assert [entry["finish_reason"] for entry in record["meta"]["iterations_detail"]] == [
        "tool_calls",
        "tool_calls",
        "stop",
    ]
    assert record["meta"]["iterations_detail"][0] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "latency_ms": record["meta"]["iterations_detail"][0]["latency_ms"],
        "finish_reason": "tool_calls",
    }
    # Every request of the loop counts, and the summary totals its tokens.
    assert summary["total_api_calls"] == 3
    assert (summary["total_prompt_tokens"], summary["total_completion_tokens"]) == (30, 15)
    assert len(state.calls) == 3


def test_simple_lookup_runs_two_iterations(tmp_path, api, capsys):
    url, _ = api(scripted(calls(("lookup", {"key": "employees"})), "The company has 142 employees."))
    records, _ = run(
        tmp_path, url, [{"question": "How many employees are there?", "answer": "142"}], capsys
    )

    assert records[0]["output"] == {"answer": "The company has 142 employees."}
    assert records[0]["result"]["passed"] is True
    assert records[0]["result"]["iterations"] == 2
    assert records[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]


def test_tool_definitions_and_results_reach_the_api(tmp_path, api, capsys):
    url, state = api(scripted(calls(("lookup", {"key": "employees"})), "142 employees."))
    run(tmp_path, url, [{"question": "How many employees?", "answer": "142"}], capsys)

    assert [tool["function"]["name"] for tool in state.calls[0]["tools"]] == ["lookup", "calculate"]
    assert state.calls[0]["tools"][0]["function"]["parameters"] == TOOLS[0]["parameters"]
    assistant, result = state.calls[1]["messages"][-2:]
    assert assistant["tool_calls"][0]["function"] == {
        "name": "lookup",
        "arguments": '{"key": "employees"}',
    }
    assert result["role"] == "tool" and result["content"] == "142"
    assert result["tool_call_id"] == assistant["tool_calls"][0]["id"]


def test_max_iterations_stops_the_loop_without_output(tmp_path, api, capsys):
    url, state = api(scripted(calls(("lookup", {"key": "employees"}))))
    records, summary = run(
        tmp_path, url, [REVENUE], capsys, generation={**TASK["generation"], "max_iterations": 4}
    )

    assert records[0]["output"] is None
    assert records[0]["result"]["passed"] is False
    assert records[0]["result"]["iterations"] == 4
    assert len(records[0]["result"]["tool_calls"]) == 4
    assert records[0]["meta"]["finish_reason"] == "max_iterations"
    assert len(records[0]["meta"]["iterations_detail"]) == 4
    assert len(state.calls) == 4
    assert (summary["passed"], summary["failed"]) == (0, 1)


def test_unknown_key_falls_back_to_the_handler_default(tmp_path, api, capsys):
    url, _ = api(scripted(calls(("lookup", {"key": "profit"})), "I could not find it."))
    records, _ = run(tmp_path, url, [REVENUE], capsys)

    assert records[0]["result"]["tool_calls"][0]["result"] == "KEY_NOT_FOUND"


def test_script_handler_returns_stdout_and_reports_failures(tmp_path, api, capsys):
    tools = [
        {
            "name": "python",
            "description": "Run a Python snippet",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
            "handler": {"type": "script", "command": "python3 -c", "arg_field": "code"},
        }
    ]
    url, _ = api(
        scripted(
            calls(("python", {"code": "print(6 * 7)"}), ("python", {"code": "raise SystemExit(3)"})),
            "The answer is 42.",
        )
    )
    records, _ = run(tmp_path, url, [{"question": "6 * 7?", "answer": "42"}], capsys, tools=tools)

    ran, failed = records[0]["result"]["tool_calls"]
    assert ran["result"] == "42"
    assert failed["result"].startswith("ERROR:")


def test_num_solutions_keeps_the_list_format(tmp_path, api, capsys):
    url, state = api(scripted("The company has 142 employees."))
    records, _ = run(
        tmp_path, url, [{"question": "How many employees?", "answer": "142"}], capsys,
        num_solutions=2,
    )
    record = records[0]

    assert record["output"] == [
        {"answer": "The company has 142 employees.", "icl_setup": None},
        {"answer": "The company has 142 employees.", "icl_setup": None},
    ]
    assert record["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert len(record["meta"]) == 2
    assert record["meta"][0]["evaluation_passed"] is True
    assert record["meta"][0]["icl_setup"] is None
    assert record["meta"][0]["total_tokens"] == 15
    assert len(record["meta"][0]["iterations_detail"]) == 1
    assert record["meta"][0]["finish_reason"] == "stop"
    assert len(state.calls) == 2


def test_without_evaluation_a_finished_loop_passes_as_null(tmp_path, api, capsys):
    url, _ = api(scripted(calls(("lookup", {"key": "employees"})), "142 employees."))
    records, _ = run(tmp_path, url, [{"question": "How many?"}], capsys, evaluation=None)

    assert records[0]["result"]["passed"] is None
    assert records[0]["result"]["iterations"] == 2


def test_without_evaluation_max_iterations_still_fails(tmp_path, api, capsys):
    url, _ = api(scripted(calls(("lookup", {"key": "employees"}))))
    records, _ = run(
        tmp_path, url, [{"question": "How many?"}], capsys,
        evaluation=None,
        generation={**TASK["generation"], "max_iterations": 2},
    )

    assert records[0]["output"] is None
    assert records[0]["result"]["passed"] is False


def test_loops_of_different_rows_overlap(tmp_path, api, capsys):
    """Three rows, each a tool call and an answer, must not serialise into six waits."""
    url, _ = api(
        scripted(calls(("lookup", {"key": "employees"})), "142 employees."),
        delay=0.2,
        capacity=8,
    )
    rows = [{"question": f"How many employees in office {number}?", "answer": "142"} for number in range(3)]

    started = time.monotonic()
    records, _ = run(tmp_path, url, rows, capsys)
    elapsed = time.monotonic() - started

    assert all(record["result"]["iterations"] == 2 for record in records)
    assert elapsed < 0.9  # six serialised requests would take 1.2s


def test_icl_setups_label_each_loop(tmp_path, api, capsys):
    def respond(payload, call):
        if any(message["role"] == "tool" for message in payload["messages"]):
            return "The company has 142 employees."
        return calls(("lookup", {"key": "employees"}))

    url, state = api(respond)
    icl = {
        "strategy": "round_robin",
        "setups": [
            {"name": "direct", "examples": [{"input": {"question": "Q"}, "output": "A"}]},
            {"name": "verbose", "examples": [{"input": {"question": "Q"}, "output": "A, at length"}]},
        ],
    }
    records, _ = run(
        tmp_path, url, [{"question": "How many employees?", "answer": "142"}], capsys,
        icl=icl, num_solutions=2,
    )
    record = records[0]

    assert [output["icl_setup"] for output in record["output"]] == ["direct", "verbose"]
    assert record["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert [entry["icl_setup"] for entry in record["meta"]] == ["direct", "verbose"]
    assert all(len(entry["iterations_detail"]) == 2 for entry in record["meta"])
    # Two loops of two requests each, every one carrying its setup's example turns.
    assert len(state.calls) == 4
    assert state.calls[0]["messages"][1:3] == [
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": "A"},
    ]
