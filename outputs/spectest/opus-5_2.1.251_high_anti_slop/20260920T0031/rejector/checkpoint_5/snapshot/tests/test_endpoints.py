"""Request bodies, response parsing and conversation turns of the two API shapes."""

import json
from dataclasses import replace

from test_runner import TASK

from config import CHAT, COMPLETIONS
from endpoints import ChatEndpoint, CompletionsEndpoint, build_endpoint
from tools import ToolCall, load_tools

MESSAGES = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "2 + 3?"}]

TOOLS = load_tools(
    [
        {
            "name": "lookup",
            "description": "Look up a value",
            "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
            "handler": {"type": "static_map", "mapping": {"a": "1"}},
        }
    ],
    "task.tools",
)

CHAT_TOOL_RESPONSE = {
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"key": "revenue_q1"}'},
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230},
}

TEXT_RESPONSE = {
    "choices": [{"text": "...response text...", "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250},
}


def test_chat_payload_carries_the_messages_and_tool_definitions():
    payload = ChatEndpoint().payload(MESSAGES, "gpt-4", 0.0, 512, TOOLS)
    assert payload["messages"] == MESSAGES
    assert payload["tools"] == [{"type": "function", "function": TOOLS[0].definition}]


def test_chat_payload_omits_tools_when_a_task_has_none():
    assert "tools" not in ChatEndpoint().payload(MESSAGES, "gpt-4", 0.0, 512, ())


def test_chat_reads_native_tool_calls():
    completion = ChatEndpoint().completion(CHAT_TOOL_RESPONSE, "gpt-4", latency_ms=300)
    call = completion.tool_calls[0]
    assert completion.text is None
    assert (call.id, call.name, call.args) == ("call_abc123", "lookup", {"key": "revenue_q1"})
    assert completion.meta["prompt_tokens"] == 200
    assert completion.meta["finish_reason"] == "tool_calls"


def test_chat_conversation_turns_use_the_openai_shape():
    endpoint = ChatEndpoint()
    completion = endpoint.completion(CHAT_TOOL_RESPONSE, "gpt-4", latency_ms=1)
    call = completion.tool_calls[0]

    assistant = endpoint.assistant_message(completion)
    assert assistant["role"] == "assistant" and assistant["content"] is None
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"key": "revenue_q1"}
    assert endpoint.tool_message(call, "1250000") == {
        "role": "tool",
        "tool_call_id": "call_abc123",
        "content": "1250000",
    }


def test_completions_payload_sends_a_rendered_prompt():
    payload = CompletionsEndpoint("llama3").payload(MESSAGES, "meta-llama/llama-3-70b", 0.0, 512, ())
    assert payload == {
        "model": "meta-llama/llama-3-70b",
        "prompt": (
            "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nSYS<|eot_id|>"
            "<|start_header_id|>user<|end_header_id|>\n\n2 + 3?<|eot_id|>"
            "<|start_header_id|>assistant<|end_header_id|>\n\n"
        ),
        "temperature": 0.0,
        "max_tokens": 512,
    }


def test_completions_renders_tool_definitions_into_the_prompt():
    payload = CompletionsEndpoint("chatml").payload(MESSAGES, "gpt-4", 0.0, 512, TOOLS)
    assert "tools" not in payload
    assert '"name": "lookup"' in payload["prompt"]
    assert "<tool_call>" in payload["prompt"]
    assert payload["prompt"].startswith("<|im_start|>system\nSYS\n\n")


def test_completions_adds_a_system_turn_when_a_task_has_no_system_prompt():
    prompt = CompletionsEndpoint("chatml").payload(MESSAGES[1:], "gpt-4", 0.0, 512, TOOLS)["prompt"]
    assert prompt.startswith("<|im_start|>system\nYou have access to the following tools:")


def test_completions_reads_the_choice_text():
    completion = CompletionsEndpoint("chatml").completion(TEXT_RESPONSE, "gpt-4", latency_ms=400)
    assert completion.text == "...response text..."
    assert completion.tool_calls == ()
    assert completion.meta["total_tokens"] == 250


def test_completions_reads_tool_calls_out_of_the_text():
    text = '<tool_call>\n{"name": "lookup", "arguments": {"key": "revenue_q1"}}\n</tool_call>'
    body = {"choices": [{"text": text, "finish_reason": "stop"}]}
    endpoint = CompletionsEndpoint("chatml")
    completion = endpoint.completion(body, "gpt-4", latency_ms=1)
    call = completion.tool_calls[0]

    assert (call.name, call.args) == ("lookup", {"key": "revenue_q1"})
    assert endpoint.assistant_message(completion) == {"role": "assistant", "content": text}
    assert endpoint.tool_message(call, "1250000") == {"role": "tool", "content": "1250000"}


def test_the_endpoint_follows_the_task_api_type():
    assert isinstance(build_endpoint(replace(TASK, api_type=CHAT)), ChatEndpoint)
    completions = build_endpoint(replace(TASK, api_type=COMPLETIONS, chat_template="zephyr"))
    assert isinstance(completions, CompletionsEndpoint)
    assert completions.payload(MESSAGES, "m", 0.0, 8, ())["prompt"].startswith("<|system|>")


def test_a_tool_call_keeps_its_arguments_when_handed_back():
    call = ToolCall(id="call_1", name="lookup", args={"key": "employees"})
    assert ChatEndpoint().tool_message(call, "142")["content"] == "142"
