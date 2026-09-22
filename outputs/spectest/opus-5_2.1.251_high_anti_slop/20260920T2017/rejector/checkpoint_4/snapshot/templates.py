"""Rendering a conversation into the one prompt string `/v1/completions` takes.

Chat mode posts a messages array and lets the server apply the model's own chat
template. Completions mode posts a single string, so the markers the model was
trained on are applied here instead. Tools travel in that string too: their
definitions are appended to the system message, and the model answers with the
`<tool_call>` blocks `parse_tool_calls` reads back out.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from tools import ToolCall, ToolConfig

DEFAULT_CHAT_TEMPLATE = "chatml"

TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

#: Appended to the system message so a text-mode model knows what it may call.
TOOL_INSTRUCTIONS = """

You have access to the following tools:

{definitions}

To call a tool, reply with a block of exactly this form and nothing else:
<tool_call>
{{"name": "<tool name>", "arguments": {{"<parameter>": "<value>"}}}}
</tool_call>

Each result is sent back to you; answer in plain text once you have enough."""


@dataclass(frozen=True)
class MarkerTemplate:
    """A template that wraps every message in the same per-role markers.

    `prefix` opens the prompt, `block` formats one message's `{role}` and
    `{content}`, and `suffix` hands the turn to the assistant.
    """

    prefix: str
    block: str
    suffix: str

    def render(self, messages: list[dict[str, Any]]) -> str:
        blocks = (
            self.block.format(role=message["role"], content=message_text(message))
            for message in messages
        )
        return self.prefix + "".join(blocks) + self.suffix


@dataclass(frozen=True)
class MistralTemplate:
    """Mistral marks only instructions, so the system text opens the first one.

    Assistant replies sit between instruction blocks, which is also where a tool
    result goes: it is another instruction the model is answering.
    """

    def render(self, messages: list[dict[str, Any]]) -> str:
        pending, turns = _split_system(messages)
        parts = []
        for message in turns:
            text = message_text(message)
            if message["role"] == "assistant":
                parts.append(f"{text}</s>")
                continue
            parts.append(f"[INST] {pending}{text} [/INST]")
            pending = ""
        return "".join(parts)


TEMPLATES: dict[str, MarkerTemplate | MistralTemplate] = {
    "chatml": MarkerTemplate(
        prefix="",
        block="<|im_start|>{role}\n{content}<|im_end|>\n",
        suffix="<|im_start|>assistant\n",
    ),
    "llama3": MarkerTemplate(
        prefix="<|begin_of_text|>",
        block="<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>",
        suffix="<|start_header_id|>assistant<|end_header_id|>\n\n",
    ),
    "mistral": MistralTemplate(),
    "zephyr": MarkerTemplate(
        prefix="",
        block="<|{role}|>\n{content}</s>\n",
        suffix="<|assistant|>\n",
    ),
}

CHAT_TEMPLATES = tuple(TEMPLATES)


def with_tools(
    messages: list[dict[str, Any]], tools: tuple[ToolConfig, ...]
) -> list[dict[str, Any]]:
    """Describe the tools in the system message, which text mode has no field for."""
    if not tools:
        return messages
    definitions = "\n".join(json.dumps(tool.definition["function"]) for tool in tools)
    system, *rest = messages
    described = system["content"] + TOOL_INSTRUCTIONS.format(definitions=definitions)
    return [{**system, "content": described}, *rest]


def message_text(message: dict[str, Any]) -> str:
    """One message's text, with any tool calls written back as `<tool_call>` blocks."""
    parts = [message["content"]] if message.get("content") else []
    parts += [_render_call(call["function"]) for call in message.get("tool_calls", ())]
    return "\n".join(parts)


def parse_tool_calls(text: str, prefix: str) -> tuple[ToolCall, ...]:
    """Read the tool calls out of a text response, ignoring malformed blocks.

    Text mode carries no call ids, so each call is identified by `prefix` and
    its position in the response.
    """
    calls = []
    for index, match in enumerate(TOOL_CALL_BLOCK.finditer(text), start=1):
        payload = _parse_block(match.group(1))
        if payload is not None:
            calls.append(
                ToolCall(f"{prefix}_{index}", payload["name"], payload.get("arguments", {}))
            )
    return tuple(calls)


def _parse_block(body: str) -> dict[str, Any] | None:
    """A block the model mangled is not a call; the response stands as text."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) and "name" in payload else None


def _render_call(function: dict[str, str]) -> str:
    """`function.arguments` is already a JSON string, so it is embedded as-is."""
    name = json.dumps(function["name"])
    return f'<tool_call>\n{{"name": {name}, "arguments": {function["arguments"]}}}\n</tool_call>'


def _split_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Mistral's system text, ready to prepend to the first instruction."""
    if messages and messages[0]["role"] == "system":
        return f"{messages[0]['content']}\n\n", messages[1:]
    return "", messages
