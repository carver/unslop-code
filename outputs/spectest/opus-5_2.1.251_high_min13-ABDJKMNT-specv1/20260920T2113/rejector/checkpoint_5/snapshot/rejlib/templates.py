"""Built-in chat templates: a message list rendered to a completions prompt."""

from __future__ import annotations

from dataclasses import dataclass

#: Placeholder each role marker wraps around a message's text.
CONTENT = "{content}"

ROLES = ("system", "user", "assistant", "tool")


@dataclass(frozen=True)
class MarkerTemplate:
    """A template that wraps every message in the markers of its own role.

    ``generation`` is the opening marker of the reply the model is to write, so
    a rendered prompt always ends ready for an assistant turn.
    """

    roles: dict[str, str]
    generation: str
    prefix: str = ""

    def render(self, messages: list[dict]) -> str:
        turns = "".join(
            self.roles[message["role"]].replace(CONTENT, message["content"] or "")
            for message in messages
        )
        return f"{self.prefix}{turns}{self.generation}"


@dataclass(frozen=True)
class MistralTemplate(MarkerTemplate):
    """Mistral has no system marker: the system text opens the first turn (T64)."""

    def render(self, messages: list[dict]) -> str:
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        turns = [message for message in messages if message["role"] != "system"]
        if system is not None:
            turns[0] = {**turns[0], "content": f"{system}\n\n{turns[0]['content']}"}
        return super().render(turns)


def _markers(pattern: str) -> dict[str, str]:
    """One marker per role, built from a pattern naming `{role}` and `{content}`."""
    return {role: pattern.replace("{role}", role) for role in ROLES}


#: The four templates the checkpoint evaluates; custom files are out of scope.
TEMPLATES = {
    "chatml": MarkerTemplate(
        roles=_markers(f"<|im_start|>{{role}}\n{CONTENT}<|im_end|>\n"),
        generation="<|im_start|>assistant\n",
    ),
    "llama3": MarkerTemplate(
        prefix="<|begin_of_text|>",
        roles=_markers(f"<|start_header_id|>{{role}}<|end_header_id|>\n\n{CONTENT}<|eot_id|>"),
        generation="<|start_header_id|>assistant<|end_header_id|>\n\n",
    ),
    "mistral": MistralTemplate(
        roles={
            "user": f"[INST] {CONTENT} [/INST]",
            "assistant": f"{CONTENT}</s>",
            "tool": f"[TOOL_RESULTS] {CONTENT} [/TOOL_RESULTS]",
        },
        generation="",
    ),
    "zephyr": MarkerTemplate(
        roles=_markers(f"<|{{role}}|>\n{CONTENT}</s>\n"),
        generation="<|assistant|>\n",
    ),
}

TEMPLATE_NAMES = tuple(TEMPLATES)


def render_prompt(name: str, messages: list[dict]) -> str:
    """Render a conversation into the `prompt` string of a completions request."""
    return TEMPLATES[name].render(messages)
