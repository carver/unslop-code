"""Checkpoint 4 built-in chat templates: chatml, llama3, mistral, zephyr."""

import pytest

from fake_api import FakeAPI, text_completion


SYSTEM = "Solve the math problem. Put your final answer after ####."
USER = "What is 2 + 3?"


def responder(text="#### 5"):
    def _responder(rec):
        return 200, text_completion(text)
    return _responder


def render(run_task, template, task=None, rows=None):
    """Run one row in completions mode and return the rendered prompt."""
    cfg = {"api_type": "completions", "chat_template": template}
    cfg.update(task or {})
    with FakeAPI(responder()) as server:
        run_task(server=server, task=cfg, rows=rows, check=0)
    return server.requests[0].prompt


ICL = {"setups": [{"name": "one_shot", "examples": [
    {"input": {"question": "EX"}, "output": "ANS"}]}]}


# chatml:
#   <|im_start|>system
#   {system_content}<|im_end|>
#   <|im_start|>user
#   {user_content}<|im_end|>
#   <|im_start|>assistant
def test_chatml_single_turn(run_task):
    assert render(run_task, "chatml") == (
        "<|im_start|>system\n%s<|im_end|>\n"
        "<|im_start|>user\n%s<|im_end|>\n"
        "<|im_start|>assistant\n" % (SYSTEM, USER))


# llama3:
#   <|begin_of_text|><|start_header_id|>system<|end_header_id|>
#
#   {system_content}<|eot_id|><|start_header_id|>user<|end_header_id|>
#
#   {user_content}<|eot_id|><|start_header_id|>assistant<|end_header_id|>
def test_llama3_single_turn(run_task):
    assert render(run_task, "llama3") == (
        "<|begin_of_text|>"
        "<|start_header_id|>system<|end_header_id|>\n\n%s<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\n%s<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n" % (SYSTEM, USER))


# mistral:
#   [INST] {system_content}
#
#   {user_content} [/INST]
def test_mistral_single_turn(run_task):
    assert render(run_task, "mistral") == \
        "[INST] %s\n\n%s [/INST]" % (SYSTEM, USER)


# zephyr:
#   <|system|>
#   {system_content}</s>
#   <|user|>
#   {user_content}</s>
#   <|assistant|>
def test_zephyr_single_turn(run_task):
    assert render(run_task, "zephyr") == (
        "<|system|>\n%s</s>\n<|user|>\n%s</s>\n<|assistant|>\n"
        % (SYSTEM, USER))


# "built-in templates must handle multi-turn conversations by repeating the
#  correct role markers for every message"
def test_chatml_multi_turn(run_task):
    assert render(run_task, "chatml", task={"icl": ICL}) == (
        "<|im_start|>system\n%s<|im_end|>\n"
        "<|im_start|>user\nEX<|im_end|>\n"
        "<|im_start|>assistant\nANS<|im_end|>\n"
        "<|im_start|>user\n%s<|im_end|>\n"
        "<|im_start|>assistant\n" % (SYSTEM, USER))


def test_llama3_multi_turn(run_task):
    assert render(run_task, "llama3", task={"icl": ICL}) == (
        "<|begin_of_text|>"
        "<|start_header_id|>system<|end_header_id|>\n\n%s<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\nEX<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\nANS<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\n%s<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n" % (SYSTEM, USER))


def test_mistral_multi_turn(run_task):
    assert render(run_task, "mistral", task={"icl": ICL}) == (
        "[INST] %s\n\nEX [/INST]ANS</s>[INST] %s [/INST]" % (SYSTEM, USER))


def test_zephyr_multi_turn(run_task):
    assert render(run_task, "zephyr", task={"icl": ICL}) == (
        "<|system|>\n%s</s>\n<|user|>\nEX</s>\n<|assistant|>\nANS</s>\n"
        "<|user|>\n%s</s>\n<|assistant|>\n" % (SYSTEM, USER))


# A task without `prompt.system` renders no system block at all.
@pytest.mark.parametrize("template,expected", [
    ("chatml", "<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n"),
    ("llama3", "<|begin_of_text|><|start_header_id|>user<|end_header_id|>"
               "\n\n%s<|eot_id|>"
               "<|start_header_id|>assistant<|end_header_id|>\n\n"),
    ("mistral", "[INST] %s [/INST]"),
    ("zephyr", "<|user|>\n%s</s>\n<|assistant|>\n"),
])
def test_templates_without_a_system_prompt(run_task, template, expected):
    prompt = render(run_task, template,
                    task={"prompt": {"system": None, "user": "{question}"}})
    assert prompt == expected % USER


# Placeholders are rendered from the row before the template is applied.
def test_row_fields_are_substituted_before_templating(run_task):
    prompt = render(run_task, "chatml",
                    task={"prompt": {"system": "S", "user": "Q: {question}"}},
                    rows=[{"question": "2+3?", "answer": "5"}])
    assert "Q: 2+3?" in prompt
    assert "{question}" not in prompt


# `chat_template` is irrelevant in chat mode: messages are sent as-is.
def test_chat_template_is_ignored_in_chat_mode(run_task):
    with FakeAPI() as server:
        run_task(server=server, task={"chat_template": "llama3"}, check=0)
    body = server.requests[0].body
    assert "prompt" not in body
    assert body["messages"][0]["content"] == SYSTEM
