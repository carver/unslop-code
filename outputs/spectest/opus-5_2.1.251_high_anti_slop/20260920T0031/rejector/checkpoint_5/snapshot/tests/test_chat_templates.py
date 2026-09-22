"""The built-in chat templates and the prompts they render."""

import pytest

from chat_templates import TEMPLATES, render_prompt

SINGLE_TURN = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USR"}]

MULTI_TURN = [
    {"role": "system", "content": "SYS"},
    {"role": "user", "content": "Q1"},
    {"role": "assistant", "content": "A1"},
    {"role": "user", "content": "Q2"},
]

EXPECTED = {
    "chatml": "<|im_start|>system\nSYS<|im_end|>\n<|im_start|>user\nUSR<|im_end|>\n<|im_start|>assistant\n",
    "llama3": (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nSYS<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\nUSR<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n"
    ),
    "mistral": "[INST] SYS\n\nUSR [/INST]",
    "zephyr": "<|system|>\nSYS</s>\n<|user|>\nUSR</s>\n<|assistant|>\n",
}

TOOL_MARKERS = {
    "chatml": "<|im_start|>tool\n142<|im_end|>\n",
    "llama3": "<|start_header_id|>tool<|end_header_id|>\n\n142<|eot_id|>",
    "mistral": "[TOOL_RESULTS] 142 [/TOOL_RESULTS]",
    "zephyr": "<|tool|>\n142</s>\n",
}


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_single_turn_matches_the_documented_template(name):
    assert render_prompt(name, SINGLE_TURN) == EXPECTED[name]


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_turn_is_rendered(name):
    prompt = render_prompt(name, MULTI_TURN)
    assert prompt.count("Q1") == prompt.count("A1") == prompt.count("Q2") == 1
    assert prompt.index("Q1") < prompt.index("A1") < prompt.index("Q2")


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_tool_results_are_rendered_with_their_own_marker(name):
    conversation = [*MULTI_TURN, {"role": "assistant", "content": "calling"}, {"role": "tool", "content": "142"}]
    assert TOOL_MARKERS[name] in render_prompt(name, conversation)


def test_chatml_repeats_its_markers_per_turn():
    assert render_prompt("chatml", MULTI_TURN) == (
        "<|im_start|>system\nSYS<|im_end|>\n"
        "<|im_start|>user\nQ1<|im_end|>\n"
        "<|im_start|>assistant\nA1<|im_end|>\n"
        "<|im_start|>user\nQ2<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def test_mistral_folds_the_system_prompt_into_the_first_instruction_only():
    assert render_prompt("mistral", MULTI_TURN) == "[INST] SYS\n\nQ1 [/INST]A1</s>[INST] Q2 [/INST]"


def test_a_prompt_without_a_system_turn_starts_with_the_user_turn():
    assert render_prompt("chatml", [{"role": "user", "content": "USR"}]) == (
        "<|im_start|>user\nUSR<|im_end|>\n<|im_start|>assistant\n"
    )
