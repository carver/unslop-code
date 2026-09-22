"""End-to-end CLI runs of the agentic scheme against the mock server.

The mock asks for whichever tools a row's `TOOL=<name>:<args>` markers name,
for as many rounds as `--tool-rounds` allows, then answers with the results it
was sent — so a record shows both halves of the loop.
"""

import json
import time

import yaml
from conftest import read_results, run_cli, write_jsonl

LOOKUP = {
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


def ask(key, answer):
    """A row whose question makes the mock call `lookup` for `key`."""
    return {
        "question": f'Look it up: TOOL=lookup:{{"key": "{key}"}} ANSWER={answer}',
        "answer": answer,
    }


ROWS = [ask("employees", "142"), ask("revenue_q1", "1250000"), ask("revenue_q2", "1480000")]


def write_task(tmp_path, api_url, tools=None, evaluation="default", **changes):
    generation = {"scheme": "agentic", "max_iterations": 10, "temperature": 0.0, "max_tokens": 64}
    task = {
        "name": "data_lookup",
        "api_url": api_url,
        "model": "gpt-4",
        "rpm": 600,
        "prompt": {"system": "Use the tools. Answer after ####.", "user": "{question}"},
        "generation": {**generation, **changes.pop("generation", {})},
        "output_field": "answer",
        "tools": tools if tools is not None else [LOOKUP, CALCULATE],
        **changes,
    }
    if evaluation == "default":
        evaluation = {"type": "exact_match", "answer_field": "answer", "extract": "last_number"}
    if evaluation is not None:
        task["evaluation"] = evaluation
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    return path


def run_task(tmp_path, config, *extra, rows=ROWS):
    output = tmp_path / "out.jsonl"
    data = write_jsonl(tmp_path / "data.jsonl", rows)
    process = run_cli("--config", config, "--input", data, "--output", output, *extra)
    return process, output


def test_a_tool_call_is_executed_and_fed_back(tmp_path, server):
    process, output = run_task(tmp_path, write_task(tmp_path, server()), rows=[ROWS[0]])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["result"]["iterations"] == 2, "one call, then the final answer"
    assert record["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]
    assert "RESULTS=142" in record["output"]["answer"], "the result reached the model"
    assert record["result"]["passed"] is True
    assert record["result"]["extracted_answer"] == "142"
    assert record["result"]["attempts"] == 1


def test_the_loop_reports_its_aggregated_metadata(tmp_path, server):
    process, output = run_task(tmp_path, write_task(tmp_path, server()), rows=[ROWS[0]])

    assert process.returncode == 0, process.stderr
    meta = read_results(output)[0]["meta"]
    assert meta["total_prompt_tokens"] == 20
    assert meta["total_completion_tokens"] == 10
    assert meta["total_tokens"] == 30
    assert meta["latency_ms"] >= 0
    assert meta["finish_reason"] == "stop"
    assert [detail["finish_reason"] for detail in meta["iterations_detail"]] == ["tool_calls", "stop"]
    assert all(detail["prompt_tokens"] == 10 for detail in meta["iterations_detail"])


def test_several_calls_in_one_response_are_all_executed(tmp_path, server):
    row = {
        "question": 'TOOL=lookup:{"key": "revenue_q1"} TOOL=lookup:{"key": "revenue_q2"} '
                    "ANSWER=2730000",
        "answer": "2730000",
    }
    process, output = run_task(tmp_path, write_task(tmp_path, server()), rows=[row])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"}, "result": "1250000"},
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"}, "result": "1480000"},
    ]
    assert record["result"]["iterations"] == 2


def test_each_round_of_calls_gets_its_own_iteration(tmp_path, server):
    config = write_task(tmp_path, server("--tool-rounds", "3"))
    process, output = run_task(tmp_path, config, rows=[ROWS[0]])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["result"]["iterations"] == 4
    assert [call["iteration"] for call in record["result"]["tool_calls"]] == [1, 2, 3]


def test_hitting_the_iteration_limit_writes_no_output(tmp_path, server):
    config = write_task(tmp_path, server("--tool-rounds", "99"), generation={"max_iterations": 3})
    process, output = run_task(tmp_path, config, rows=[ROWS[0]])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["output"] is None
    assert record["meta"]["finish_reason"] == "max_iterations"
    assert len(record["meta"]["iterations_detail"]) == 3
    assert record["result"]["iterations"] == 3
    assert len(record["result"]["tool_calls"]) == 3
    assert record["result"]["passed"] is False


def test_an_echo_tool_hands_its_arguments_back(tmp_path, server):
    row = {"question": 'TOOL=calculate:{"expression": "1+1"} ANSWER=2', "answer": "2"}
    process, output = run_task(tmp_path, write_task(tmp_path, server()), rows=[row])

    assert process.returncode == 0, process.stderr
    call = read_results(output)[0]["result"]["tool_calls"][0]
    assert call == {
        "iteration": 1,
        "tool": "calculate",
        "args": {"expression": "1+1"},
        "result": '{"expression": "1+1"}',
    }


def test_a_script_tool_runs_its_command(tmp_path, server):
    script = {
        "name": "python",
        "description": "Run a Python snippet",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
        "handler": {"type": "script", "command": "python3 -c", "arg_field": "code"},
    }
    row = {"question": 'TOOL=python:{"code": "print(6*7)"} ANSWER=42', "answer": "42"}
    config = write_task(tmp_path, server(), tools=[script])
    process, output = run_task(tmp_path, config, rows=[row])

    assert process.returncode == 0, process.stderr
    assert read_results(output)[0]["result"]["tool_calls"][0]["result"] == "42\n"


def test_a_row_without_evaluation_reports_a_null_verdict(tmp_path, server):
    config = write_task(tmp_path, server(), evaluation=None)
    process, output = run_task(tmp_path, config, rows=[ROWS[0]])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["result"]["passed"] is None
    assert record["result"]["iterations"] == 2


def test_several_solutions_use_the_list_format(tmp_path, server):
    config = write_task(tmp_path, server("--tool-rounds", "0"), num_solutions=2)
    process, output = run_task(tmp_path, config, rows=[ROWS[0]])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert len(record["output"]) == 2
    assert record["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert len(record["meta"]) == 2
    assert all(entry["total_prompt_tokens"] == 10 for entry in record["meta"])
    assert all(entry["finish_reason"] == "stop" for entry in record["meta"])
    assert all(entry["evaluation_passed"] is True for entry in record["meta"])
    assert all(entry["icl_setup"] is None for entry in record["meta"])


def test_the_list_format_counts_loops_not_requests(tmp_path, server):
    """Two loops of two requests each still report two attempts."""
    config = write_task(tmp_path, server(), num_solutions=2)
    process, output = run_task(tmp_path, config, rows=[ROWS[0]])

    assert process.returncode == 0, process.stderr
    assert read_results(output)[0]["result"]["attempts"] == 2
    assert json.loads(process.stdout)["total_api_calls"] == 4


def test_a_loop_that_runs_out_of_iterations_emits_no_list_item(tmp_path, server):
    config = write_task(tmp_path, server("--tool-rounds", "99"), evaluation=None,
                        num_solutions=2, generation={"max_iterations": 2})
    process, output = run_task(tmp_path, config, rows=[ROWS[0]])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["output"] == []
    assert record["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert [entry["finish_reason"] for entry in record["meta"]] == ["max_iterations"] * 2
    assert all(entry["evaluation_passed"] is None for entry in record["meta"])


def test_icl_examples_are_sent_with_the_loop(tmp_path, server):
    icl = {"setups": [{"name": "demo", "examples": [{"input": {"question": "q"}, "output": "a"}]}]}
    process, output = run_task(tmp_path, write_task(tmp_path, server(), icl=icl), rows=[ROWS[0]])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert "ICL=1:a" in record["output"][0]["answer"]
    assert record["output"][0]["icl_setup"] == "demo"
    assert record["meta"][0]["iterations_detail"], "the loop's metadata is kept per solution"


def test_rows_of_a_batch_overlap_in_flight(tmp_path, server):
    """Three two-request loops on three workers cost two delays, not six."""
    delay = 0.6
    config = write_task(tmp_path, server(workers=3, delay=delay))
    started = time.monotonic()
    process, output = run_task(tmp_path, config)
    elapsed = time.monotonic() - started

    assert process.returncode == 0, process.stderr
    assert all(record["result"]["iterations"] == 2 for record in read_results(output))
    assert elapsed < 4 * delay, "the rows did not serialise behind each other"
