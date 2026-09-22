"""Spec section: Part 4 / Completions Mode (built-in chat templates)."""
from __future__ import annotations

from conftest import COT_SETUP, base_config, icl_config
from mock_server import MockAPI, text_completion


ROW = {"question": "What is 15 + 27?", "answer": "42"}
SYSTEM = "Solve the math problem. Put your final answer after ####."
USER = ROW["question"]
ANSWER = "#### 42"


def text_always(content):
    body = text_completion(content)
    return lambda req, i: (200, body)


def render(run_tool, write_config, write_input, template, cfg=None):
    """Return the prompt string the tool sent for a single row."""
    with MockAPI(text_always(ANSWER)) as api:
        builder = cfg or base_config
        config = write_config(builder(api.url, api_type="completions",
                                      chat_template=template))
        data = write_input([ROW])
        res = run_tool(config, data)
        prompts = [r["prompt"] for r in api.requests]
    assert res.returncode == 0, res
    return prompts[0]


# ---------------------------------------------------------------------------
# Phrase: "`chatml`: <|im_start|>system\n{system_content}<|im_end|>\n
#          <|im_start|>user\n{user_content}<|im_end|>\n<|im_start|>assistant"
# Context: Part 4 / Completions Mode / Built-in templates.
# ---------------------------------------------------------------------------
def test_chatml_template(run_tool, write_config, write_input):
    prompt = render(run_tool, write_config, write_input, "chatml")
    assert prompt == (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{USER}<|im_end|>\n"
        f"<|im_start|>assistant\n")


# ---------------------------------------------------------------------------
# Phrase: "`llama3`: <|begin_of_text|><|start_header_id|>system<|end_header_id|>
#          ... <|eot_id|><|start_header_id|>assistant<|end_header_id|>"
# Context: Part 4 / Completions Mode / Built-in templates.
# ---------------------------------------------------------------------------
def test_llama3_template(run_tool, write_config, write_input):
    prompt = render(run_tool, write_config, write_input, "llama3")
    assert prompt == (
        "<|begin_of_text|>"
        f"<|start_header_id|>system<|end_header_id|>\n\n{SYSTEM}<|eot_id|>"
        f"<|start_header_id|>user<|end_header_id|>\n\n{USER}<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n")


# ---------------------------------------------------------------------------
# Phrase: "`mistral`: [INST] {system_content}\n\n{user_content} [/INST]"
# Context: Part 4 / Completions Mode / Built-in templates.
# ---------------------------------------------------------------------------
def test_mistral_template(run_tool, write_config, write_input):
    prompt = render(run_tool, write_config, write_input, "mistral")
    assert prompt == f"[INST] {SYSTEM}\n\n{USER} [/INST]"


# ---------------------------------------------------------------------------
# Phrase: "`zephyr`: <|system|>\n{system_content}</s>\n<|user|>\n
#          {user_content}</s>\n<|assistant|>"
# Context: Part 4 / Completions Mode / Built-in templates.
# ---------------------------------------------------------------------------
def test_zephyr_template(run_tool, write_config, write_input):
    prompt = render(run_tool, write_config, write_input, "zephyr")
    assert prompt == (
        f"<|system|>\n{SYSTEM}</s>\n"
        f"<|user|>\n{USER}</s>\n"
        f"<|assistant|>\n")


# ---------------------------------------------------------------------------
# Phrase: "built-in templates must handle multi-turn conversations by
#          repeating the correct role markers for every message"
# Context: Part 4 / Completions Mode rules.  ICL examples make the
#          conversation multi-turn.
# ---------------------------------------------------------------------------
def multi_turn_prompt(run_tool, write_config, write_input, template):
    def builder(api_url, **kw):
        return icl_config(api_url, [COT_SETUP], k=1, **kw)
    return render(run_tool, write_config, write_input, template, cfg=builder)


def test_chatml_multi_turn(run_tool, write_config, write_input):
    shot = COT_SETUP["examples"][0]
    prompt = multi_turn_prompt(run_tool, write_config, write_input, "chatml")
    assert prompt == (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{shot['input']['question']}<|im_end|>\n"
        f"<|im_start|>assistant\n{shot['output']}<|im_end|>\n"
        f"<|im_start|>user\n{USER}<|im_end|>\n"
        f"<|im_start|>assistant\n")


def test_llama3_multi_turn(run_tool, write_config, write_input):
    shot = COT_SETUP["examples"][0]
    prompt = multi_turn_prompt(run_tool, write_config, write_input, "llama3")
    assert prompt.count("<|begin_of_text|>") == 1
    assert prompt.count("<|start_header_id|>user<|end_header_id|>") == 2
    assert prompt.count("<|start_header_id|>assistant<|end_header_id|>") == 2
    assert (f"<|start_header_id|>assistant<|end_header_id|>\n\n"
            f"{shot['output']}<|eot_id|>") in prompt
    assert prompt.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")


def test_zephyr_multi_turn(run_tool, write_config, write_input):
    shot = COT_SETUP["examples"][0]
    prompt = multi_turn_prompt(run_tool, write_config, write_input, "zephyr")
    assert prompt == (
        f"<|system|>\n{SYSTEM}</s>\n"
        f"<|user|>\n{shot['input']['question']}</s>\n"
        f"<|assistant|>\n{shot['output']}</s>\n"
        f"<|user|>\n{USER}</s>\n"
        f"<|assistant|>\n")


def test_mistral_multi_turn(run_tool, write_config, write_input):
    shot = COT_SETUP["examples"][0]
    prompt = multi_turn_prompt(run_tool, write_config, write_input, "mistral")
    # system content rides along with the first instruction block; later user
    # turns get their own [INST] block (AMBIGUITIES T83)
    assert prompt == (
        f"[INST] {SYSTEM}\n\n{shot['input']['question']} [/INST]"
        f" {shot['output']}</s>"
        f"[INST] {USER} [/INST]")


# ---------------------------------------------------------------------------
# Phrase: "{system_content}" (templates show a system block)
# Context: Part 4 - a task without `prompt.system` renders no system block
#          (AMBIGUITIES T82).
# ---------------------------------------------------------------------------
def test_template_without_system_message(run_tool, write_config, write_input):
    def builder(api_url, **kw):
        return base_config(api_url, prompt={"system": None,
                                            "user": "{question}"}, **kw)
    prompt = render(run_tool, write_config, write_input, "chatml", cfg=builder)
    assert prompt == (f"<|im_start|>user\n{USER}<|im_end|>\n"
                      f"<|im_start|>assistant\n")


# Context: the default template is `chatml` when `chat_template` is unset
# (AMBIGUITIES T80).
def test_default_template_is_chatml(run_tool, write_config, write_input):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(base_config(api.url, api_type="completions"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        prompt = api.requests[0]["prompt"]
    assert res.returncode == 0, res
    assert prompt.startswith("<|im_start|>system\n")
