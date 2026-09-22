"""The request body and response shape of each endpoint's transport."""

from client import ChatTransport, CompletionsTransport
from templates import TEMPLATES
from tools import EchoHandler, ToolConfig

MESSAGES = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "How many?"},
]

TOOL = ToolConfig("lookup", "Look a value up", {"type": "object"}, EchoHandler())


def test_a_chat_request_sends_the_messages_array():
    assert ChatTransport().payload(MESSAGES, ()) == {"messages": MESSAGES}


def test_a_chat_request_sends_tool_definitions_of_their_own():
    payload = ChatTransport().payload(MESSAGES, (TOOL,))
    assert payload["tools"] == [TOOL.definition]


def test_a_completions_request_sends_one_rendered_prompt():
    payload = CompletionsTransport(TEMPLATES["llama3"]).payload(MESSAGES, ())

    assert list(payload) == ["prompt"]
    assert payload["prompt"].startswith("<|begin_of_text|>")
    assert payload["prompt"].endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")


def test_a_completions_request_writes_its_tools_into_the_prompt():
    payload = CompletionsTransport(TEMPLATES["chatml"]).payload(MESSAGES, (TOOL,))
    assert '"name": "lookup"' in payload["prompt"]


def test_a_chat_response_is_read_from_its_message():
    choice = {"message": {"role": "assistant", "content": "142 of them."}}
    assert ChatTransport().parse(choice) == ("142 of them.", ())


def test_chat_tool_calls_arrive_with_their_arguments_parsed():
    choice = {
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
    text, calls = ChatTransport().parse(choice)

    assert text is None
    assert (calls[0].id, calls[0].name, calls[0].arguments) == (
        "call_abc123",
        "lookup",
        {"key": "revenue_q1"},
    )


def test_a_completions_response_is_read_from_its_text():
    transport = CompletionsTransport(TEMPLATES["chatml"])
    assert transport.parse({"text": "142 of them.", "finish_reason": "stop"}) == ("142 of them.", ())


def test_completions_tool_calls_are_numbered_per_response():
    transport = CompletionsTransport(TEMPLATES["chatml"])
    block = '<tool_call>\n{"name": "lookup", "arguments": {"key": "a"}}\n</tool_call>'

    first = transport.parse({"text": block})[1][0]
    second = transport.parse({"text": block})[1][0]
    assert first.id != second.id
