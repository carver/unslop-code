"""The four built-in chat templates, rendered to a completions prompt string."""

from __future__ import annotations

import pytest

from rejlib.templates import render_prompt

SYSTEM = "You are helpful."
USER = "What is 2 + 3?"
SIMPLE = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}]
MULTI_TURN = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": "demo?"},
    {"role": "assistant", "content": "demo!"},
    {"role": "user", "content": USER},
]


# "chatml"
def test_chatml_matches_the_spec_block():
    assert render_prompt("chatml", SIMPLE) == (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{USER}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


# "llama3"
def test_llama3_matches_the_spec_block():
    assert render_prompt("llama3", SIMPLE) == (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        f"{SYSTEM}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        f"{USER}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


# "mistral"
def test_mistral_matches_the_spec_block():
    assert render_prompt("mistral", SIMPLE) == f"[INST] {SYSTEM}\n\n{USER} [/INST]"


# "zephyr"
def test_zephyr_matches_the_spec_block():
    assert render_prompt("zephyr", SIMPLE) == (
        f"<|system|>\n{SYSTEM}</s>\n"
        f"<|user|>\n{USER}</s>\n"
        "<|assistant|>\n"
    )


# "built-in templates must handle multi-turn conversations by repeating the
#  correct role markers for every message"
def test_chatml_repeats_role_markers():
    assert render_prompt("chatml", MULTI_TURN) == (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        "<|im_start|>user\ndemo?<|im_end|>\n"
        "<|im_start|>assistant\ndemo!<|im_end|>\n"
        f"<|im_start|>user\n{USER}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def test_llama3_repeats_role_markers():
    assert render_prompt("llama3", MULTI_TURN) == (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        f"{SYSTEM}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        "demo?<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        "demo!<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        f"{USER}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def test_zephyr_repeats_role_markers():
    assert render_prompt("zephyr", MULTI_TURN) == (
        f"<|system|>\n{SYSTEM}</s>\n"
        "<|user|>\ndemo?</s>\n"
        "<|assistant|>\ndemo!</s>\n"
        f"<|user|>\n{USER}</s>\n"
        "<|assistant|>\n"
    )


# Mistral has no system role: the system text opens the first instruction block
# and later turns alternate instruction and reply.
def test_mistral_repeats_instruction_blocks():
    assert render_prompt("mistral", MULTI_TURN) == (
        f"[INST] {SYSTEM}\n\ndemo? [/INST]demo!</s>[INST] {USER} [/INST]"
    )


@pytest.mark.parametrize("name", ["chatml", "llama3", "mistral", "zephyr"])
def test_a_conversation_without_a_system_message_renders(name):
    prompt = render_prompt(name, [{"role": "user", "content": USER}])
    assert USER in prompt
    assert SYSTEM not in prompt


# "feed the results back into the next prompt iteration using the template's
#  tool-role formatting"
@pytest.mark.parametrize("name,marker", [
    ("chatml", "<|im_start|>tool\n1250000<|im_end|>\n"),
    ("llama3", "<|start_header_id|>tool<|end_header_id|>\n\n1250000<|eot_id|>"),
    ("zephyr", "<|tool|>\n1250000</s>\n"),
    ("mistral", "[TOOL_RESULTS] 1250000 [/TOOL_RESULTS]"),
])
def test_tool_results_use_the_template_tool_markers(name, marker):
    messages = [
        {"role": "user", "content": USER},
        {"role": "assistant", "content": "<tool_call>..."},
        {"role": "tool", "content": "1250000"},
    ]
    assert marker in render_prompt(name, messages)


def test_an_unknown_template_name_is_rejected():
    with pytest.raises(KeyError):
        render_prompt("alpaca", SIMPLE)
