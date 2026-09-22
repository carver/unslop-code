"""Part 4: template-driven requests against `/v1/completions`."""
import pytest

from conftest import icl_block, icl_setup, make_config
from mock_api import MockAPI, completion_response

ROWS = [{"question": "What is 2+2?", "answer": "4"}]
SYSTEM = "SYS"
USER = "What is 2+2?"


def completions(text="The answer is 4", **kw):
    """A responder that always answers with a text completion body."""
    return lambda payload, i: (200, completion_response(text, **kw))


def prompt_for(run_tool, system=SYSTEM, template=None, rows=None, icl=None,
               responder=None, **kw):
    with MockAPI(responder or completions()) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions",
                                   chat_template=template, system=system,
                                   icl=icl, **kw), rows or ROWS)
    assert run.returncode == 0, run.stderr
    return api.calls[0]["prompt"], run


# Spec: "When `api_type` is `"completions"`, send requests to
#        `{api_url}/v1/completions` with a rendered prompt string instead of
#        a messages array."
# Context: Completions Mode.
def test_request_goes_to_the_completions_endpoint(run_tool):
    with MockAPI(completions()) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions"),
                       ROWS)
    assert run.returncode == 0, run.stderr
    assert api.paths == ["/v1/completions"]
    assert "messages" not in api.calls[0]


# Spec: "completions requests send `prompt`, `temperature`, `max_tokens`, and
#        `model`"
# Context: Completions Mode rules / request shape.
def test_request_body_has_exactly_the_four_fields(run_tool):
    with MockAPI(completions()) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions",
                                   model="meta-llama/llama-3-70b",
                                   max_tokens=512), ROWS)
    assert run.returncode == 0, run.stderr
    payload = api.calls[0]
    assert set(payload) == {"model", "prompt", "temperature", "max_tokens"}
    assert payload["model"] == "meta-llama/llama-3-70b"
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 512


# Spec: "completions responses return `choices[].text`, not
#        `choices[].message`"
# Context: Completions Mode rules / response shape.
def test_output_is_read_from_choices_text(run_tool):
    with MockAPI(completions("the answer is 4")) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions"),
                       ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] == {"solution": "the answer is 4"}
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "4"


def test_usage_and_finish_reason_come_from_the_completions_body(run_tool):
    responder = completions("4", prompt_tokens=200, completion_tokens=50,
                            finish_reason="length")
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions"),
                       ROWS)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["meta"]["prompt_tokens"] == 200
    assert run.rows[0]["meta"]["completion_tokens"] == 50
    assert run.rows[0]["meta"]["finish_reason"] == "length"
    assert run.summary["total_prompt_tokens"] == 200


# Spec: the `chatml` built-in template.
# Context: Built-in templates.
def test_chatml_template(run_tool):
    prompt, _ = prompt_for(run_tool, template="chatml")
    assert prompt == ("<|im_start|>system\n"
                      "SYS<|im_end|>\n"
                      "<|im_start|>user\n"
                      "What is 2+2?<|im_end|>\n"
                      "<|im_start|>assistant\n")


# Spec: the `llama3` built-in template.
# Context: Built-in templates.
def test_llama3_template(run_tool):
    prompt, _ = prompt_for(run_tool, template="llama3")
    assert prompt == ("<|begin_of_text|><|start_header_id|>system"
                      "<|end_header_id|>\n\n"
                      "SYS<|eot_id|><|start_header_id|>user<|end_header_id|>"
                      "\n\n"
                      "What is 2+2?<|eot_id|><|start_header_id|>assistant"
                      "<|end_header_id|>\n\n")


# Spec: the `mistral` built-in template.
# Context: Built-in templates.
def test_mistral_template(run_tool):
    prompt, _ = prompt_for(run_tool, template="mistral")
    assert prompt == "[INST] SYS\n\nWhat is 2+2? [/INST]"


# Spec: the `zephyr` built-in template.
# Context: Built-in templates.
def test_zephyr_template(run_tool):
    prompt, _ = prompt_for(run_tool, template="zephyr")
    assert prompt == ("<|system|>\n"
                      "SYS</s>\n"
                      "<|user|>\n"
                      "What is 2+2?</s>\n"
                      "<|assistant|>\n")


# Spec: `chat_template` defaults when `api_type` is completions but no
#       template is named.
# Context: Completions Mode config.
def test_default_template_is_chatml(run_tool):
    prompt, _ = prompt_for(run_tool, template=None)
    assert prompt.startswith("<|im_start|>system\nSYS<|im_end|>")


# Spec: "built-in templates must handle multi-turn conversations by repeating
#        the correct role markers for every message"
# Context: Completions Mode rules.
def test_chatml_multi_turn_repeats_role_markers(run_tool):
    icl = icl_block([icl_setup("demo", [("EX_Q", "EX_A")])])
    prompt, _ = prompt_for(run_tool, template="chatml", icl=icl)
    assert prompt == ("<|im_start|>system\n"
                      "SYS<|im_end|>\n"
                      "<|im_start|>user\n"
                      "EX_Q<|im_end|>\n"
                      "<|im_start|>assistant\n"
                      "EX_A<|im_end|>\n"
                      "<|im_start|>user\n"
                      "What is 2+2?<|im_end|>\n"
                      "<|im_start|>assistant\n")


def test_llama3_multi_turn_repeats_role_markers(run_tool):
    icl = icl_block([icl_setup("demo", [("EX_Q", "EX_A")])])
    prompt, _ = prompt_for(run_tool, template="llama3", icl=icl)
    assert prompt.count("<|start_header_id|>user<|end_header_id|>") == 2
    assert prompt.count("<|start_header_id|>assistant<|end_header_id|>") == 2
    assert prompt.count("<|begin_of_text|>") == 1
    assert ("<|start_header_id|>assistant<|end_header_id|>\n\nEX_A<|eot_id|>"
            in prompt)
    assert prompt.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")


def test_zephyr_multi_turn_repeats_role_markers(run_tool):
    icl = icl_block([icl_setup("demo", [("EX_Q", "EX_A")])])
    prompt, _ = prompt_for(run_tool, template="zephyr", icl=icl)
    assert "<|assistant|>\nEX_A</s>\n" in prompt
    assert prompt.count("<|user|>") == 2
    assert prompt.endswith("<|assistant|>\n")


def test_mistral_multi_turn_wraps_each_user_turn(run_tool):
    icl = icl_block([icl_setup("demo", [("EX_Q", "EX_A")])])
    prompt, _ = prompt_for(run_tool, template="mistral", icl=icl)
    assert prompt == ("[INST] SYS\n\nEX_Q [/INST]EX_A</s>"
                      "[INST] What is 2+2? [/INST]")


# Spec: a task with no system prompt still renders.
# Context: Built-in templates (`{system_content}` has no message to fill it).
def test_chatml_without_a_system_message(run_tool):
    prompt, _ = prompt_for(run_tool, template="chatml", system=None)
    assert prompt == ("<|im_start|>user\n"
                      "What is 2+2?<|im_end|>\n"
                      "<|im_start|>assistant\n")


def test_llama3_without_a_system_message(run_tool):
    prompt, _ = prompt_for(run_tool, template="llama3", system=None)
    assert prompt.startswith("<|begin_of_text|><|start_header_id|>user"
                             "<|end_header_id|>\n\nWhat is 2+2?")
    assert "system" not in prompt


def test_mistral_without_a_system_message(run_tool):
    prompt, _ = prompt_for(run_tool, template="mistral", system=None)
    assert prompt == "[INST] What is 2+2? [/INST]"


def test_zephyr_without_a_system_message(run_tool):
    prompt, _ = prompt_for(run_tool, template="zephyr", system=None)
    assert prompt == "<|user|>\nWhat is 2+2?</s>\n<|assistant|>\n"


# Spec: the rendered prompt carries the row's substituted fields.
# Context: Completions Mode (a rendered prompt string).
def test_prompt_renders_row_fields(run_tool):
    rows = [{"question": "Who wrote Dune?", "answer": "Herbert"}]
    prompt, _ = prompt_for(run_tool, template="chatml", rows=rows)
    assert "Who wrote Dune?" in prompt


# Spec: completions mode works for the existing schemes and evaluation.
# Context: "Existing behavior from earlier parts is unchanged unless stated."
def test_rejection_sampling_works_in_completions_mode(run_tool):
    texts = ["nope 0", "nope 1", "the answer is 4"]

    def responder(payload, i):
        text = texts[min(i, len(texts) - 1)]
        return 200, completion_response(text)

    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions",
                                   scheme="rejection", temperature=0.7, n=5),
                       ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["result"]["attempts"] == 3
    assert row["result"]["passed"] is True
    assert len(row["meta"]) == 3


def test_multiple_rows_each_get_their_own_prompt(run_tool):
    rows = [{"question": "q one", "answer": "4"},
            {"question": "q two", "answer": "4"}]
    with MockAPI(completions("4")) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions"),
                       rows)
    assert run.returncode == 0, run.stderr
    prompts = sorted(c["prompt"] for c in api.calls)
    assert len(prompts) == 2
    assert "q one" in prompts[0] and "q two" in prompts[1]
