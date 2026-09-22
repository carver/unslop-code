"""Tests for ``/v1/completions`` mode: the built-in templates and template-driven runs."""

import yaml

from chat_templates import render_prompt
from test_agentic import LOOKUP, asking

CONVERSATION = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "What is 2+2?"},
]

ROWS = [{"question": "two plus six?", "answer": "8"}]
EVALUATION = {"type": "exact_match", "answer_field": "answer", "extract": "last_number"}


def config(url, **task):
    """Build a single completions-mode task pointed at the mock server."""
    return yaml.safe_dump(
        {
            "task": {
                "name": "gsm8k",
                "api_url": url,
                "model": "mock-model",
                "rpm": 600,
                "prompt": {"system": "Solve the problem.", "user": "{question}"},
                "generation": {"scheme": "greedy", "max_tokens": 64},
                "evaluation": EVALUATION,
                "output_field": "solution",
                **task,
            }
        }
    )


def test_chatml_template():
    assert render_prompt("chatml", CONVERSATION) == (
        "<|im_start|>system\nYou are helpful.<|im_end|>\n"
        "<|im_start|>user\nWhat is 2+2?<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def test_llama3_template():
    assert render_prompt("llama3", CONVERSATION) == (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        "You are helpful.<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        "What is 2+2?<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def test_mistral_template():
    assert render_prompt("mistral", CONVERSATION) == "[INST] You are helpful.\n\nWhat is 2+2? [/INST]"


def test_zephyr_template():
    assert render_prompt("zephyr", CONVERSATION) == (
        "<|system|>\nYou are helpful.</s>\n<|user|>\nWhat is 2+2?</s>\n<|assistant|>\n"
    )


def test_templates_repeat_markers_for_every_turn():
    multi_turn = [
        *CONVERSATION,
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "And 3+3?"},
    ]

    assert render_prompt("chatml", multi_turn).count("<|im_start|>") == 5
    assert render_prompt("llama3", multi_turn).count("<|start_header_id|>") == 5
    assert render_prompt("zephyr", multi_turn).count("</s>") == 4
    assert render_prompt("mistral", multi_turn) == (
        "[INST] You are helpful.\n\nWhat is 2+2? [/INST]4</s>[INST] And 3+3? [/INST]"
    )


def test_completions_run_uses_the_rendered_prompt(mock_server, run_cli):
    server = mock_server()

    completed, summary, results = run_cli(
        config(server.url, api_type="completions", chat_template="llama3"), ROWS
    )

    assert completed.returncode == 0, completed.stderr
    solution = results[0]["output"]["solution"]
    assert solution.startswith("echo: <|begin_of_text|><|start_header_id|>system<|end_header_id|>")
    assert "two plus six?" in solution
    assert results[0]["result"]["passed"] is True
    assert summary["total_api_calls"] == 1


def test_cli_flags_override_the_configured_api_type(mock_server, run_cli):
    server = mock_server()

    _, _, results = run_cli(
        config(server.url), ROWS, "--api-type", "completions", "--chat-template", "zephyr"
    )

    assert results[0]["output"]["solution"].startswith("echo: <|system|>\nSolve the problem.</s>")


def test_unknown_chat_template_is_rejected(mock_server, run_cli):
    server = mock_server()

    completed, _, _ = run_cli(config(server.url), ROWS, "--chat-template", "alpaca")

    assert completed.returncode == 1
    assert "chat_template must be one of" in completed.stderr


def test_agentic_loop_in_completions_mode(mock_server, run_cli):
    server = mock_server()
    rows = [asking("lookup", ("key", "employees"), "How many employees?", "142")]
    task = {
        "generation": {"scheme": "agentic", "temperature": 0.0, "max_tokens": 64},
        "prompt": {"system": "Use the tools to answer.", "user": "{question}"},
        "tools": [LOOKUP],
        "api_type": "completions",
        "chat_template": "chatml",
    }

    completed, _, results = run_cli(config(server.url, **task), rows)

    assert completed.returncode == 0, completed.stderr
    assert results[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]
    assert results[0]["result"]["iterations"] == 2
    assert results[0]["result"]["passed"] is True
    # The second prompt carried the tool definitions, the call, and its result back to the model.
    solution = results[0]["output"]["solution"]
    assert '"name": "lookup"' in solution
    assert "<|im_start|>tool\n<tool_response>\n142\n</tool_response>" in solution
