"""The `/v1/completions` mode: the built-in chat templates and runs that use them."""

import json

import pytest
import yaml
from mock_server import start_mock_server

import rejector
from templates import TEMPLATES
from tools import Handler, Tool

CONVERSATION = [
    {"role": "system", "content": "SYS"},
    {"role": "user", "content": "USR"},
]

RENDERED = {
    "chatml": "<|im_start|>system\nSYS<|im_end|>\n<|im_start|>user\nUSR<|im_end|>\n<|im_start|>assistant\n",
    "llama3": (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nSYS<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\nUSR<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n"
    ),
    "mistral": "[INST] SYS\n\nUSR [/INST]",
    "zephyr": "<|system|>\nSYS</s>\n<|user|>\nUSR</s>\n<|assistant|>\n",
}

TASK = {
    "name": "gsm8k",
    "model": "meta-llama/llama-3-70b",
    "rpm": 600,
    "api_type": "completions",
    "chat_template": "llama3",
    "prompt": {"system": "Solve the math problem.", "user": "{question}"},
    "generation": {"scheme": "greedy", "max_tokens": 512},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
}

ROW = {"question": "What is 2 + 3?", "answer": "5"}


@pytest.fixture
def api():
    servers = []

    def start(responder, delay=0.0):
        url, state, shutdown = start_mock_server(responder, delay=delay)
        servers.append(shutdown)
        return url, state

    yield start
    for shutdown in servers:
        shutdown()


def run(tmp_path, url, rows, capsys, extra=(), **task):
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
            *extra,
        ]
    ) == 0
    records = [json.loads(line) for line in (tmp_path / "out.jsonl").read_text().splitlines()]
    return records, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_templates_render_the_documented_prompt(name):
    assert TEMPLATES[name].render(CONVERSATION) == RENDERED[name]


def test_templates_repeat_their_markers_for_every_turn():
    conversation = [
        *CONVERSATION,
        {"role": "assistant", "content": "A1"},
        {"role": "user", "content": "U2"},
    ]

    assert TEMPLATES["chatml"].render(conversation) == (
        "<|im_start|>system\nSYS<|im_end|>\n"
        "<|im_start|>user\nUSR<|im_end|>\n"
        "<|im_start|>assistant\nA1<|im_end|>\n"
        "<|im_start|>user\nU2<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
    assert TEMPLATES["mistral"].render(conversation) == "[INST] SYS\n\nUSR [/INST] A1</s>[INST] U2 [/INST]"
    assert TEMPLATES["zephyr"].render(conversation) == (
        "<|system|>\nSYS</s>\n<|user|>\nUSR</s>\n<|assistant|>\nA1</s>\n<|user|>\nU2</s>\n<|assistant|>\n"
    )


def test_a_template_renders_tools_and_their_results():
    tool = Tool("lookup", "Look a key up", {"type": "object", "required": ["key"]}, Handler("echo"))
    conversation = [
        *CONVERSATION,
        {"role": "assistant", "content": '<tool_call>\n{"name": "lookup"}\n</tool_call>'},
        {"role": "tool", "name": "lookup", "content": "142"},
    ]

    prompt = TEMPLATES["chatml"].render(conversation, [tool])

    assert "Look a key up" in prompt and "<tool_call>" in prompt
    assert '<|im_start|>tool\n<tool_response>\n{"name": "lookup", "content": "142"}\n</tool_response>' in prompt


def test_completions_run_reads_the_text_choice(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "2 + 3 = 5\n#### 5")
    records, summary = run(tmp_path, url, [ROW], capsys)

    assert records[0]["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert records[0]["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}
    assert summary["total"] == summary["passed"] == 1
    assert state.calls[0] == {
        "model": "meta-llama/llama-3-70b",
        "prompt": RENDERED["llama3"].replace("SYS", "Solve the math problem.").replace("USR", ROW["question"]),
        "temperature": 0.0,
        "max_tokens": 512,
    }


def test_cli_flags_switch_the_endpoint_and_template(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 5")
    records, _ = run(
        tmp_path, url, [ROW], capsys,
        extra=["--api-type", "completions", "--chat-template", "chatml"],
        api_type="chat",
        chat_template="llama3",
    )

    assert records[0]["result"]["passed"] is True
    assert state.calls[0]["prompt"].startswith("<|im_start|>system\nSolve the math problem.<|im_end|>")


def test_an_agentic_loop_feeds_tool_results_back_into_the_prompt(tmp_path, api, capsys):
    tools = [
        {
            "name": "lookup",
            "description": "Look up a value by key",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
            "handler": {"type": "static_map", "mapping": {"employees": "142"}},
        }
    ]

    def respond(payload, call):
        if "<tool_response>" in payload["prompt"]:
            return "The company has 142 employees."
        return [{"name": "lookup", "arguments": {"key": "employees"}}]

    url, state = api(respond)
    records, _ = run(
        tmp_path, url, [{"question": "How many employees?", "answer": "142"}], capsys,
        generation={"scheme": "agentic", "max_iterations": 5, "max_tokens": 512},
        output_field="answer",
        tools=tools,
    )

    assert records[0]["output"] == {"answer": "The company has 142 employees."}
    assert records[0]["result"]["iterations"] == 2
    assert records[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]
    # The second prompt replays the call and its result with the template's markers.
    assert "Look up a value by key" in state.calls[1]["prompt"]
    assert '<|start_header_id|>ipython<|end_header_id|>\n\n<tool_response>' in state.calls[1]["prompt"]
    assert '{"name": "lookup", "content": "142"}' in state.calls[1]["prompt"]


def test_an_unmapped_key_uses_the_default_tool_result(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: '<tool_call>\n{"name": "lookup", "arguments": {"key": "x"}}\n</tool_call>')
    records, _ = run(
        tmp_path, url, [{"question": "How many?", "answer": "1"}], capsys,
        generation={"scheme": "agentic", "max_iterations": 1, "max_tokens": 512},
        output_field="answer",
        tools=[
            {
                "name": "lookup",
                "description": "Look up a value by key",
                "parameters": {"type": "object", "required": ["key"]},
                "handler": {"type": "static_map", "mapping": {"employees": "142"}},
            }
        ],
    )

    assert records[0]["result"]["tool_calls"][0]["result"] == "NOT_FOUND"
    assert records[0]["meta"]["finish_reason"] == "max_iterations"
