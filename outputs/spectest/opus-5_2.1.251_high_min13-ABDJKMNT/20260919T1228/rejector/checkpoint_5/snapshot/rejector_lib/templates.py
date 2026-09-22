"""Built-in chat templates: a conversation rendered into one prompt string.

`/v1/completions` takes text rather than messages, so each template turns the
same message list the chat endpoint would receive into the markers its model
was trained on, and ends with the marker that opens the assistant's turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial


@dataclass(frozen=True)
class MarkedTemplate:
    """A template that wraps every message in the same role markers."""

    prefix: str
    turn: str
    generation: str


CHATML = MarkedTemplate(
    prefix="",
    turn="<|im_start|>{role}\n{content}<|im_end|>\n",
    generation="<|im_start|>assistant\n",
)

LLAMA3 = MarkedTemplate(
    prefix="<|begin_of_text|>",
    turn="<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>",
    generation="<|start_header_id|>assistant<|end_header_id|>\n\n",
)

ZEPHYR = MarkedTemplate(
    prefix="",
    turn="<|{role}|>\n{content}</s>\n",
    generation="<|assistant|>\n",
)


def _render_marked(template: MarkedTemplate, messages: list[dict]) -> str:
    """Repeat the template's role markers over every message in order."""
    turns = "".join(
        template.turn.format(role=message["role"], content=message["content"] or "")
        for message in messages
    )
    return template.prefix + turns + template.generation


def _render_mistral(messages: list[dict]) -> str:
    """Mistral has only instruction blocks: system text joins the first one.

    Every non-assistant turn opens its own `[INST] ... [/INST]`, so tool
    results reach the model the same way a user turn does.
    """
    rendered = []
    leading = [message["content"] for message in messages if message["role"] == "system"]
    for message in messages:
        if message["role"] == "system":
            continue
        if message["role"] == "assistant":
            rendered.append(f" {message['content'] or ''}</s>")
            continue
        rendered.append(
            "[INST] " + "\n\n".join([*leading, message["content"]]) + " [/INST]"
        )
        leading = []
    return "".join(rendered)


RENDERERS = {
    "chatml": partial(_render_marked, CHATML),
    "llama3": partial(_render_marked, LLAMA3),
    "mistral": _render_mistral,
    "zephyr": partial(_render_marked, ZEPHYR),
}

TEMPLATE_NAMES = tuple(RENDERERS)


def render_prompt(name: str, messages: list[dict]) -> str:
    """Render `messages` with the named built-in template."""
    return RENDERERS[name](messages)
