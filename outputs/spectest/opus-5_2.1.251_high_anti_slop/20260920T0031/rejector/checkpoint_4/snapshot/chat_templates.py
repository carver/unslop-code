"""Built-in chat templates that fold a conversation into a single prompt string.

`/v1/completions` takes a prompt instead of a messages array, so the
conversation is written out with the role markers of the model family being
served. Every template repeats its markers for as many turns as the
conversation has, tool results included.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from templates import Message

SYSTEM = "system"
USER = "user"
ASSISTANT = "assistant"
TOOL = "tool"
ROLES = (SYSTEM, USER, ASSISTANT, TOOL)


@dataclass(frozen=True)
class MarkerTemplate:
    """A template that wraps every message in an opening and closing marker for its role.

    The rendered prompt ends with the assistant's opening marker, which is where
    the model continues from.
    """

    preamble: str
    markers: dict[str, tuple[str, str]]

    def render(self, messages: Sequence[Message]) -> str:
        turns = "".join(self._turn(message) for message in messages)
        return self.preamble + turns + self.markers[ASSISTANT][0]

    def _turn(self, message: Message) -> str:
        opening, closing = self.markers[message["role"]]
        return f"{opening}{message['content']}{closing}"


CHATML = MarkerTemplate(preamble="", markers={role: (f"<|im_start|>{role}\n", "<|im_end|>\n") for role in ROLES})

LLAMA3 = MarkerTemplate(
    preamble="<|begin_of_text|>",
    markers={role: (f"<|start_header_id|>{role}<|end_header_id|>\n\n", "<|eot_id|>") for role in ROLES},
)

ZEPHYR = MarkerTemplate(preamble="", markers={role: (f"<|{role}|>\n", "</s>\n") for role in ROLES})

#: Mistral has no system marker: the system prompt opens the first instruction instead.
MISTRAL_TURNS = {
    USER: "[INST] {content} [/INST]",
    ASSISTANT: "{content}</s>",
    TOOL: "[TOOL_RESULTS] {content} [/TOOL_RESULTS]",
}


def render_mistral(messages: Sequence[Message]) -> str:
    """`[INST] … [/INST]` turns, with the system prompt carried into the first instruction."""
    pending = "".join(f"{message['content']}\n\n" for message in messages if message["role"] == SYSTEM)
    turns = []
    for message in messages:
        if message["role"] == USER:
            turns.append(MISTRAL_TURNS[USER].format(content=pending + message["content"]))
            pending = ""
        elif message["role"] in MISTRAL_TURNS:
            turns.append(MISTRAL_TURNS[message["role"]].format(content=message["content"]))
    return "".join(turns)


TEMPLATES: dict[str, Callable[[Sequence[Message]], str]] = {
    "chatml": CHATML.render,
    "llama3": LLAMA3.render,
    "mistral": render_mistral,
    "zephyr": ZEPHYR.render,
}

DEFAULT_TEMPLATE = "chatml"


def render_prompt(template: str, messages: Sequence[Message]) -> str:
    """Render a conversation with the named built-in template."""
    return TEMPLATES[template](messages)
