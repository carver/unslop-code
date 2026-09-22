"""The four built-in chat templates, single-turn and multi-turn."""

from __future__ import annotations

from conftest import base_config, icl_setup
from fake_server import FakeAPIServer, Reply, text_completion

ROW = {"question": "2+3?", "answer": "5"}
SYSTEM = "Solve the math problem. Put your final answer after ####."
EXAMPLE_Q = "example 1"
EXAMPLE_A = "demo answer"


def _answers(payload, index):
    return Reply(text_completion("#### 5"))


def _prompt(write_config, write_input, run_cli, template: str, *, icl: bool = False) -> str:
    """Render one row through `template` and return the prompt the API saw."""
    config_map = base_config("", api_type="completions", chat_template=template)
    if icl:
        config_map["task"]["icl"] = {"setups": [icl_setup("demo", EXAMPLE_A)]}
    with FakeAPIServer(_answers) as api:
        config_map["task"]["api_url"] = api.url
        run_cli(write_config(config_map), write_input([ROW]))
        payloads = api.payloads
    return payloads[0]["prompt"]


# Spec: the `chatml` template block
def test_chatml_single_turn(write_config, write_input, run_cli):
    prompt = _prompt(write_config, write_input, run_cli, "chatml")

    assert prompt == (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{ROW['question']}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


# Spec: "built-in templates must handle multi-turn conversations by repeating
# the correct role markers for every message"
def test_chatml_repeats_markers_for_every_message(write_config, write_input, run_cli):
    prompt = _prompt(write_config, write_input, run_cli, "chatml", icl=True)

    assert prompt == (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{EXAMPLE_Q}<|im_end|>\n"
        f"<|im_start|>assistant\n{EXAMPLE_A}<|im_end|>\n"
        f"<|im_start|>user\n{ROW['question']}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


# Spec: the `llama3` template block
def test_llama3_single_turn(write_config, write_input, run_cli):
    prompt = _prompt(write_config, write_input, run_cli, "llama3")

    assert prompt == (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        f"{SYSTEM}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        f"{ROW['question']}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"
    )


# Spec: "repeating the correct role markers for every message" - llama3
def test_llama3_multi_turn(write_config, write_input, run_cli):
    prompt = _prompt(write_config, write_input, run_cli, "llama3", icl=True)

    assert prompt.count("<|begin_of_text|>") == 1
    assert prompt.count("<|start_header_id|>user<|end_header_id|>") == 2
    assert f"<|start_header_id|>assistant<|end_header_id|>\n\n{EXAMPLE_A}<|eot_id|>" in prompt
    assert prompt.endswith("<|start_header_id|>assistant<|end_header_id|>\n")


# Spec: the `mistral` template block
def test_mistral_single_turn(write_config, write_input, run_cli):
    prompt = _prompt(write_config, write_input, run_cli, "mistral")

    assert prompt == f"[INST] {SYSTEM}\n\n{ROW['question']} [/INST]\n"


# Spec: "repeating the correct role markers for every message" - mistral has
# no assistant marker, so its answers close the instruction block
def test_mistral_multi_turn(write_config, write_input, run_cli):
    prompt = _prompt(write_config, write_input, run_cli, "mistral", icl=True)

    assert prompt.startswith(f"[INST] {SYSTEM}\n\n{EXAMPLE_Q} [/INST]")
    assert EXAMPLE_A in prompt
    assert prompt.count("[INST]") == 2
    assert prompt.endswith(f"[INST] {ROW['question']} [/INST]\n")


# Spec: the `zephyr` template block
def test_zephyr_single_turn(write_config, write_input, run_cli):
    prompt = _prompt(write_config, write_input, run_cli, "zephyr")

    assert prompt == (
        f"<|system|>\n{SYSTEM}</s>\n"
        f"<|user|>\n{ROW['question']}</s>\n"
        "<|assistant|>\n"
    )


# Spec: "repeating the correct role markers for every message" - zephyr
def test_zephyr_multi_turn(write_config, write_input, run_cli):
    prompt = _prompt(write_config, write_input, run_cli, "zephyr", icl=True)

    assert prompt == (
        f"<|system|>\n{SYSTEM}</s>\n"
        f"<|user|>\n{EXAMPLE_Q}</s>\n"
        f"<|assistant|>\n{EXAMPLE_A}</s>\n"
        f"<|user|>\n{ROW['question']}</s>\n"
        "<|assistant|>\n"
    )


# Spec: "{system_content}" - a task without a system prompt renders only the
# turns it has
def test_template_without_a_system_message(write_config, write_input, run_cli):
    config_map = base_config("", api_type="completions", chat_template="chatml")
    del config_map["task"]["prompt"]["system"]
    with FakeAPIServer(_answers) as api:
        config_map["task"]["api_url"] = api.url
        run_cli(write_config(config_map), write_input([ROW]))
        payloads = api.payloads

    assert payloads[0]["prompt"] == (
        f"<|im_start|>user\n{ROW['question']}<|im_end|>\n<|im_start|>assistant\n"
    )
