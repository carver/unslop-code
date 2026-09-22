"""End-to-end CLI runs against `/v1/completions` with a rendered chat template."""

import pytest
import yaml
from conftest import read_results, run_cli, write_jsonl

from templates import CHAT_TEMPLATES

ROWS = [{"question": f"Row {i}: compute ANSWER={i + 1}", "answer": str(i + 1)} for i in range(3)]

TOOL_ROW = {
    "question": 'Look it up: TOOL=lookup:{"key": "employees"} ANSWER=142',
    "answer": "142",
}

LOOKUP = {
    "name": "lookup",
    "description": "Look up a value in the database by key",
    "parameters": {
        "type": "object",
        "properties": {"key": {"type": "string", "description": "The database key"}},
        "required": ["key"],
    },
    "handler": {"type": "static_map", "mapping": {"employees": "142"}, "default": "KEY_NOT_FOUND"},
}


def write_task(tmp_path, api_url, **changes):
    task = {
        "name": "mock_task",
        "api_url": api_url,
        "model": "meta-llama/llama-3-70b",
        "rpm": 600,
        "prompt": {"system": "Solve it. Answer after ####.", "user": "{question}"},
        "generation": {"scheme": "greedy", "max_tokens": 64},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "solution",
        **changes,
    }
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    return path


def run_task(tmp_path, config, *extra, rows=ROWS):
    output = tmp_path / "out.jsonl"
    data = write_jsonl(tmp_path / "data.jsonl", rows)
    process = run_cli("--config", config, "--input", data, "--output", output, *extra)
    return process, output


def test_cli_flags_switch_a_chat_task_to_completions(tmp_path, server):
    config = write_task(tmp_path, server())
    process, output = run_task(tmp_path, config, "--api-type", "completions",
                               "--chat-template", "llama3")

    assert process.returncode == 0, process.stderr
    records = read_results(output)
    assert [record["output"]["solution"] for record in records] == [
        f"Working it out.\n#### {row['answer']}" for row in ROWS
    ]
    assert all(record["result"]["passed"] for record in records)


def test_the_config_can_ask_for_completions_itself(tmp_path, server):
    config = write_task(tmp_path, server(), api_type="completions", chat_template="mistral")
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    assert read_results(output)[0]["result"]["extracted_answer"] == "1"


@pytest.mark.parametrize("template", CHAT_TEMPLATES)
def test_every_built_in_template_completes_a_run(tmp_path, server, template):
    config = write_task(tmp_path, server(), api_type="completions", chat_template=template)
    process, output = run_task(tmp_path, config, rows=ROWS[:1])

    assert process.returncode == 0, process.stderr
    assert read_results(output)[0]["result"]["passed"] is True


def test_a_chat_task_still_posts_to_the_chat_endpoint(tmp_path, server):
    """The mock answers `/v1/completions` too, so the default must be unchanged."""
    process, output = run_task(tmp_path, write_task(tmp_path, server()), rows=ROWS[:1])

    assert process.returncode == 0, process.stderr
    assert read_results(output)[0]["output"] == {"solution": "Working it out.\n#### 1"}


def test_an_agentic_loop_runs_over_text_tool_calls(tmp_path, server):
    config = write_task(
        tmp_path,
        server(),
        api_type="completions",
        chat_template="chatml",
        generation={"scheme": "agentic", "max_iterations": 5, "max_tokens": 64},
        output_field="answer",
        tools=[LOOKUP],
    )
    process, output = run_task(tmp_path, config, rows=[TOOL_ROW])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["result"]["iterations"] == 2
    assert record["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]
    assert "142" in record["output"]["answer"], "the result was rendered back into the prompt"
    assert record["result"]["passed"] is True


def test_an_unknown_template_is_rejected(tmp_path, server):
    config = write_task(tmp_path, server(), api_type="completions")
    process, output = run_task(tmp_path, config, "--chat-template", "alpaca")

    assert process.returncode == 1
    assert "chat_template must be one of" in process.stderr
    assert not output.exists()
