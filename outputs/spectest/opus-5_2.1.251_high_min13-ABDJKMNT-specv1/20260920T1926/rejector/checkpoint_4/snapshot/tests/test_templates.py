"""The four built-in chat templates that flatten messages into a prompt."""

from __future__ import annotations

import pytest

from taskrunner.templates import TEMPLATES, render_prompt

SYSTEM = {"role": "system", "content": "SYS"}
USER = {"role": "user", "content": "USR"}
ASSISTANT = {"role": "assistant", "content": "ANS"}
TOOL = {"role": "tool", "name": "lookup", "content": "142"}


# Spec: the `chatml` built-in template block.
# Context: Completions Mode / Built-in templates.
def test_chatml_renders_the_documented_block():
    assert render_prompt("chatml", [SYSTEM, USER]) == (
        "<|im_start|>system\n"
        "SYS<|im_end|>\n"
        "<|im_start|>user\n"
        "USR<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


# Spec: the `llama3` built-in template block.
# Context: Completions Mode / Built-in templates.
def test_llama3_renders_the_documented_block():
    assert render_prompt("llama3", [SYSTEM, USER]) == (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        "SYS<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        "USR<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


# Spec: the `mistral` built-in template block.
# Context: Completions Mode / Built-in templates.
def test_mistral_renders_the_documented_block():
    assert render_prompt("mistral", [SYSTEM, USER]) == "[INST] SYS\n\nUSR [/INST]"


# Spec: the `zephyr` built-in template block.
# Context: Completions Mode / Built-in templates.
def test_zephyr_renders_the_documented_block():
    assert render_prompt("zephyr", [SYSTEM, USER]) == (
        "<|system|>\nSYS</s>\n<|user|>\nUSR</s>\n<|assistant|>\n"
    )


# Spec: "built-in templates must handle multi-turn conversations by repeating
# the correct role markers for every message"
# Context: Completions Mode / Rules.
@pytest.mark.parametrize("name", TEMPLATES)
def test_every_template_keeps_all_turns_in_order(name):
    prompt = render_prompt(name, [SYSTEM, USER, ASSISTANT, {"role": "user", "content": "U2"}])
    positions = [prompt.index(part) for part in ("SYS", "USR", "ANS", "U2")]
    assert positions == sorted(positions)


# Spec: "repeating the correct role markers for every message"
# Context: Completions Mode / Rules; a second user turn repeats the marker.
def test_marker_templates_repeat_role_markers_per_message():
    prompt = render_prompt("chatml", [USER, ASSISTANT, {"role": "user", "content": "U2"}])
    assert prompt.count("<|im_start|>user\n") == 2
    assert prompt.count("<|im_start|>assistant\n") == 2  # the turn plus the generation cue
    assert prompt.count("<|im_end|>\n") == 3


# Spec: "repeating the correct role markers for every message"
# Context: Completions Mode / Rules; llama3 header blocks.
def test_llama3_repeats_header_blocks_and_emits_one_bos():
    prompt = render_prompt("llama3", [SYSTEM, USER, ASSISTANT, USER])
    assert prompt.count("<|begin_of_text|>") == 1
    assert prompt.count("<|start_header_id|>user<|end_header_id|>") == 2
    assert prompt.count("<|eot_id|>") == 4


# Spec: "repeating the correct role markers for every message"
# Context: Completions Mode / Rules; mistral has no assistant marker, so an
# assistant turn closes the instruction block and the next user turn opens one.
def test_mistral_opens_a_new_instruction_block_per_user_turn():
    prompt = render_prompt("mistral", [SYSTEM, USER, ASSISTANT, {"role": "user", "content": "U2"}])
    assert prompt == "[INST] SYS\n\nUSR [/INST] ANS</s>[INST] U2 [/INST]"


# Spec: "feed the results back into the next prompt iteration using the
# template's tool-role formatting"
# Context: Agentic behavior in completions mode.
@pytest.mark.parametrize("name", TEMPLATES)
def test_tool_results_reach_the_prompt(name):
    prompt = render_prompt(name, [SYSTEM, USER, ASSISTANT, TOOL])
    assert "142" in prompt


# Spec: "using the template's tool-role formatting"
# Context: Agentic behavior in completions mode; marker templates name the role.
def test_marker_templates_use_the_tool_role_marker():
    assert "<|im_start|>tool\n142<|im_end|>\n" in render_prompt("chatml", [USER, ASSISTANT, TOOL])
    assert "<|tool|>\n142</s>\n" in render_prompt("zephyr", [USER, ASSISTANT, TOOL])
    assert (
        "<|start_header_id|>tool<|end_header_id|>\n\n142<|eot_id|>"
        in render_prompt("llama3", [USER, ASSISTANT, TOOL])
    )


# Spec: "this checkpoint evaluates only the four built-in templates above"
# Context: Completions Mode / Rules.
def test_only_the_four_built_ins_exist():
    assert TEMPLATES == ("chatml", "llama3", "mistral", "zephyr")
