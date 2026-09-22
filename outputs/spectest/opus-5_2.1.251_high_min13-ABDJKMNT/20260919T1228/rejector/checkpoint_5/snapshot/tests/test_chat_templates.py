"""The four built-in chat templates, rendered straight from the messages."""

from __future__ import annotations

import pytest

from rejector_lib.templates import render_prompt

SYSTEM = {"role": "system", "content": "SYS"}
USER = {"role": "user", "content": "USR"}
TURNS = [SYSTEM, USER, {"role": "assistant", "content": "A1"}, {"role": "user", "content": "U2"}]
TOOL = [SYSTEM, USER, {"role": "assistant", "content": "CALL"}, {"role": "tool", "content": "142"}]


# Spec: the `chatml` template.
def test_chatml_renders_the_documented_prompt():
    assert render_prompt("chatml", [SYSTEM, USER]) == (
        "<|im_start|>system\n"
        "SYS<|im_end|>\n"
        "<|im_start|>user\n"
        "USR<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


# Spec: the `llama3` template.
def test_llama3_renders_the_documented_prompt():
    assert render_prompt("llama3", [SYSTEM, USER]) == (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        "SYS<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        "USR<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


# Spec: the `mistral` template.
def test_mistral_renders_the_documented_prompt():
    assert render_prompt("mistral", [SYSTEM, USER]) == "[INST] SYS\n\nUSR [/INST]"


# Spec: the `zephyr` template.
def test_zephyr_renders_the_documented_prompt():
    assert render_prompt("zephyr", [SYSTEM, USER]) == (
        "<|system|>\nSYS</s>\n<|user|>\nUSR</s>\n<|assistant|>\n"
    )


# Spec: "built-in templates must handle multi-turn conversations by repeating
# the correct role markers for every message".
def test_chatml_repeats_role_markers():
    prompt = render_prompt("chatml", TURNS)
    assert prompt == (
        "<|im_start|>system\nSYS<|im_end|>\n"
        "<|im_start|>user\nUSR<|im_end|>\n"
        "<|im_start|>assistant\nA1<|im_end|>\n"
        "<|im_start|>user\nU2<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


# Spec: "repeating the correct role markers for every message".
def test_llama3_repeats_role_markers():
    prompt = render_prompt("llama3", TURNS)
    assert prompt.count("<|begin_of_text|>") == 1
    assert prompt.count("<|start_header_id|>user<|end_header_id|>") == 2
    assert prompt.count("<|start_header_id|>assistant<|end_header_id|>") == 2
    assert prompt.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")


# Spec: "repeating the correct role markers for every message" -- zephyr's
# markers wrap each turn.
def test_zephyr_repeats_role_markers():
    assert render_prompt("zephyr", TURNS) == (
        "<|system|>\nSYS</s>\n"
        "<|user|>\nUSR</s>\n"
        "<|assistant|>\nA1</s>\n"
        "<|user|>\nU2</s>\n"
        "<|assistant|>\n"
    )


# Spec: "repeating the correct role markers for every message" -- mistral wraps
# each user turn in its own instruction block. (T68)
def test_mistral_repeats_instruction_blocks():
    prompt = render_prompt("mistral", TURNS)
    assert prompt == "[INST] SYS\n\nUSR [/INST] A1</s>[INST] U2 [/INST]"


# Spec: agentic completions feed tool results back "using the template's
# tool-role formatting". (T69)
def test_tool_messages_use_a_tool_role_marker():
    assert "<|im_start|>tool\n142<|im_end|>" in render_prompt("chatml", TOOL)
    assert "<|tool|>\n142</s>" in render_prompt("zephyr", TOOL)
    assert "<|start_header_id|>tool<|end_header_id|>\n\n142<|eot_id|>" in render_prompt(
        "llama3", TOOL
    )


# Spec: only "chatml", "llama3", "mistral" and "zephyr" are built in.
def test_unknown_template_is_rejected():
    with pytest.raises(KeyError):
        render_prompt("alpaca", [SYSTEM, USER])


# Spec: the templates place the system content first; a task without a system
# prompt simply has no system turn.
def test_prompt_without_a_system_message():
    assert render_prompt("chatml", [USER]) == (
        "<|im_start|>user\nUSR<|im_end|>\n<|im_start|>assistant\n"
    )
