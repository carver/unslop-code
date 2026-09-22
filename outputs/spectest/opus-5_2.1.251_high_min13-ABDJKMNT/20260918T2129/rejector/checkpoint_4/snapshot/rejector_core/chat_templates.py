"""Rendering a chat conversation into one `/v1/completions` prompt string.

Every built-in template repeats its role markers for each message of the
conversation and ends with the marker that opens the assistant's next turn.
"""

from __future__ import annotations

from collections.abc import Sequence

from .tools import ToolSpec, describe_tools

_LLAMA3_HEADER = "<|start_header_id|>{role}<|end_header_id|>"
_MISTRAL_INSTRUCTION = "[INST] {content} [/INST]"
_MISTRAL_TURNS = {
    "assistant": "{content}</s>",
    "tool": "[TOOL_RESULTS] {content} [/TOOL_RESULTS]",
}


def _chatml(messages: list[dict]) -> str:
    turns = "".join(f"<|im_start|>{m['role']}\n{_content(m)}<|im_end|>\n" for m in messages)
    return f"{turns}<|im_start|>assistant\n"


def _llama3(messages: list[dict]) -> str:
    turns = "".join(
        f"{_LLAMA3_HEADER.format(role=m['role'])}\n\n{_content(m)}<|eot_id|>" for m in messages
    )
    return f"<|begin_of_text|>{turns}{_LLAMA3_HEADER.format(role='assistant')}\n"


def _zephyr(messages: list[dict]) -> str:
    turns = "".join(f"<|{m['role']}|>\n{_content(m)}</s>\n" for m in messages)
    return f"{turns}<|assistant|>\n"


def _mistral(messages: list[dict]) -> str:
    """Mistral has no role markers: the system prompt opens the first
    instruction block, and answers simply follow the block that asked."""
    pending = "".join(f"{_content(m)}\n\n" for m in messages if m["role"] == "system")
    turns = []
    for message in (m for m in messages if m["role"] != "system"):
        content = _content(message)
        if message["role"] == "user":
            content, pending = f"{pending}{content}", ""
        turns.append(_MISTRAL_TURNS.get(message["role"], _MISTRAL_INSTRUCTION).format(content=content))
    return "".join(turns) + "\n"


_RENDERERS = {"chatml": _chatml, "llama3": _llama3, "mistral": _mistral, "zephyr": _zephyr}

CHAT_TEMPLATES = tuple(_RENDERERS)


def render_prompt(template: str, messages: list[dict], tools: Sequence[ToolSpec] = ()) -> str:
    """Render one conversation with a built-in template.

    A completions request cannot carry a native `tools` field, so an agentic
    task's tools are declared inside the system message instead.
    """
    return _RENDERERS[template](_with_tools(messages, tools) if tools else messages)


def _with_tools(messages: list[dict], tools: Sequence[ToolSpec]) -> list[dict]:
    block = describe_tools(tools)
    if messages and messages[0]["role"] == "system":
        head = {**messages[0], "content": f"{_content(messages[0])}\n\n{block}"}
        return [head, *messages[1:]]
    return [{"role": "system", "content": block}, *messages]


def _content(message: dict) -> str:
    """A message's text; an assistant turn that only calls tools has none."""
    return message.get("content") or ""
