"""The built-in chat templates and the text form of a tool call."""

import pytest

from templates import TEMPLATES, parse_tool_calls, with_tools
from tools import EchoHandler, ToolConfig

SIMPLE = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Hello?"},
]

MULTI_TURN = SIMPLE + [
    {"role": "assistant", "content": "Hi there."},
    {"role": "user", "content": "Again?"},
]

CALL = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "lookup", "arguments": '{"key": "employees"}'},
}

WITH_TOOL_CALL = SIMPLE + [
    {"role": "assistant", "content": None, "tool_calls": [CALL]},
    {"role": "tool", "tool_call_id": "call_1", "content": "142"},
]


def render(name, messages):
    return TEMPLATES[name].render(messages)


def test_chatml_matches_the_documented_shape():
    assert render("chatml", SIMPLE) == (
        "<|im_start|>system\n"
        "You are helpful.<|im_end|>\n"
        "<|im_start|>user\n"
        "Hello?<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def test_llama3_matches_the_documented_shape():
    assert render("llama3", SIMPLE) == (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        "You are helpful.<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        "Hello?<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def test_mistral_folds_the_system_text_into_the_first_instruction():
    assert render("mistral", SIMPLE) == "[INST] You are helpful.\n\nHello? [/INST]"


def test_zephyr_matches_the_documented_shape():
    assert render("zephyr", SIMPLE) == (
        "<|system|>\nYou are helpful.</s>\n<|user|>\nHello?</s>\n<|assistant|>\n"
    )


@pytest.mark.parametrize("name", list(TEMPLATES))
def test_every_template_repeats_its_markers_for_extra_turns(name):
    once = render(name, SIMPLE)
    twice = render(name, MULTI_TURN)
    assert len(twice) > len(once)
    assert "Hi there." in twice and "Again?" in twice


def test_mistral_marks_each_extra_turn():
    assert render("mistral", MULTI_TURN) == (
        "[INST] You are helpful.\n\nHello? [/INST]Hi there.</s>[INST] Again? [/INST]"
    )


@pytest.mark.parametrize("name", list(TEMPLATES))
def test_a_tool_call_and_its_result_are_rendered_into_the_prompt(name):
    prompt = render(name, WITH_TOOL_CALL)
    assert '<tool_call>\n{"name": "lookup", "arguments": {"key": "employees"}}\n</tool_call>' in prompt
    assert "142" in prompt


def test_the_tool_role_gets_its_own_marker():
    assert "<|im_start|>tool\n142<|im_end|>" in render("chatml", WITH_TOOL_CALL)
    assert "<|tool|>\n142</s>" in render("zephyr", WITH_TOOL_CALL)


def test_tool_definitions_are_appended_to_the_system_message():
    tool = ToolConfig("lookup", "Look a value up", {"type": "object"}, EchoHandler())
    messages = with_tools(SIMPLE, (tool,))

    assert messages[0]["content"].startswith("You are helpful.")
    assert '"name": "lookup"' in messages[0]["content"]
    assert "<tool_call>" in messages[0]["content"]
    assert messages[1:] == SIMPLE[1:], "only the system message changes"
    assert SIMPLE[0]["content"] == "You are helpful.", "the original is left alone"


def test_no_tools_leaves_the_conversation_untouched():
    assert with_tools(SIMPLE, ()) is SIMPLE


def test_tool_calls_are_read_back_out_of_a_text_response():
    text = (
        'Let me look.\n<tool_call>\n{"name": "lookup", "arguments": {"key": "a"}}\n</tool_call>\n'
        '<tool_call>\n{"name": "lookup", "arguments": {"key": "b"}}\n</tool_call>'
    )
    calls = parse_tool_calls(text, "call_7")

    assert [call.name for call in calls] == ["lookup", "lookup"]
    assert [call.arguments["key"] for call in calls] == ["a", "b"]
    assert [call.id for call in calls] == ["call_7_1", "call_7_2"]


def test_plain_text_holds_no_tool_calls():
    assert parse_tool_calls("The company has 142 employees.", "call_1") == ()


def test_a_malformed_block_is_not_a_tool_call():
    assert parse_tool_calls("<tool_call>\n{not json}\n</tool_call>", "call_1") == ()
