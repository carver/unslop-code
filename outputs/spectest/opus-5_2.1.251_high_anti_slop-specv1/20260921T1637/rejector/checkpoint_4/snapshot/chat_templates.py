"""Built-in chat templates that flatten a conversation into a completions prompt.

``/v1/completions`` takes a single prompt string, so the messages a chat request
would carry are rendered with the model family's own role markers, and the
prompt ends with the marker that invites the assistant's reply.
"""

from dataclasses import dataclass
from typing import Any, Callable

TEMPLATES = ("chatml", "llama3", "mistral", "zephyr")
DEFAULT_TEMPLATE = "chatml"

Messages = list[dict[str, Any]]


@dataclass(frozen=True)
class _Markers:
    """A template that wraps every turn in the same role markers.

    ``turn`` carries ``{role}`` and ``{content}`` placeholders, ``generation``
    is the trailing marker, and ``prefix`` opens the prompt.
    """

    turn: str
    generation: str
    prefix: str = ""

    def render(self, messages: Messages) -> str:
        """Render one marker per message, repeating them for a multi-turn conversation."""
        turns = "".join(
            self.turn.replace("{role}", message["role"]).replace("{content}", message["content"])
            for message in messages
        )
        return f"{self.prefix}{turns}{self.generation}"


def render_prompt(template: str, messages: Messages) -> str:
    """Flatten ``messages`` into the prompt string that ``template`` describes."""
    return _TEMPLATES[template](messages)


def _render_mistral(messages: Messages) -> str:
    """Mistral has no role markers: system text opens the first instruction block.

    User and tool turns become ``[INST] ... [/INST]`` blocks and assistant turns
    are plain text closed by ``</s>``.
    """
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rendered: list[str] = []
    for message in messages:
        if message["role"] == "system":
            continue
        if message["role"] == "assistant":
            rendered.append(f"{message['content']}</s>")
            continue
        opening = f"{system}\n\n" if system and not rendered else ""
        rendered.append(f"[INST] {opening}{message['content']} [/INST]")
    return "".join(rendered)


#: Each built-in template as a callable turning a conversation into a prompt.
_TEMPLATES: dict[str, Callable[[Messages], str]] = {
    "chatml": _Markers(
        turn="<|im_start|>{role}\n{content}<|im_end|>\n",
        generation="<|im_start|>assistant\n",
    ).render,
    "llama3": _Markers(
        prefix="<|begin_of_text|>",
        turn="<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>",
        generation="<|start_header_id|>assistant<|end_header_id|>\n\n",
    ).render,
    "mistral": _render_mistral,
    "zephyr": _Markers(
        turn="<|{role}|>\n{content}</s>\n",
        generation="<|assistant|>\n",
    ).render,
}
