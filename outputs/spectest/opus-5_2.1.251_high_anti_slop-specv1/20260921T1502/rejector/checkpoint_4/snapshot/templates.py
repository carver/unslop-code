"""Chat templates that render a conversation into one completions prompt.

`/v1/completions` takes a single prompt string, so a task in that mode renders
its messages through the template its server was trained on. The templates also
carry the text protocol that stands in for native tool calling there: the tool
definitions go into the system turn and the calls are parsed back out of the
reply.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Sequence

from tools import Tool, ToolCall, parse_arguments

# The block a model writes to call a tool when the endpoint has no `tools` field.
TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

_CALL_FORMAT = (
    "To use a tool, reply with one block per call, and nothing else:\n"
    '<tool_call>\n{"name": "<tool name>", "arguments": {"<name>": "<value>"}}\n</tool_call>\n'
    "Each result comes back in a tool message. Once you can answer, reply with "
    "the answer as plain text and no tool call block."
)


@dataclass(frozen=True)
class ChatTemplate:
    """The role markers of one server's prompt format.

    `roles` maps a message role to the text wrapping its content, `prefix` opens
    the prompt and `generation` is the trailing header that invites the
    assistant's reply. `merge_system` marks formats without a system role, which
    fold the system message into the first user turn instead.
    """

    prefix: str
    roles: dict[str, tuple[str, str]]
    generation: str
    merge_system: bool = False

    def render(self, messages: list[dict], tools: Sequence[Tool] = ()) -> str:
        """Render a whole conversation, tool definitions included, into one prompt."""
        turns = _with_tools(messages, tools)
        if self.merge_system:
            turns = _folded(turns)
        return self.prefix + "".join(map(self._turn, turns)) + self.generation

    def _turn(self, message: dict) -> str:
        opening, closing = self.roles[message["role"]]
        return f"{opening}{_content(message)}{closing}"


TEMPLATES = {
    "chatml": ChatTemplate(
        prefix="",
        roles={
            "system": ("<|im_start|>system\n", "<|im_end|>\n"),
            "user": ("<|im_start|>user\n", "<|im_end|>\n"),
            "assistant": ("<|im_start|>assistant\n", "<|im_end|>\n"),
            "tool": ("<|im_start|>tool\n", "<|im_end|>\n"),
        },
        generation="<|im_start|>assistant\n",
    ),
    "llama3": ChatTemplate(
        prefix="<|begin_of_text|>",
        roles={
            "system": ("<|start_header_id|>system<|end_header_id|>\n\n", "<|eot_id|>"),
            "user": ("<|start_header_id|>user<|end_header_id|>\n\n", "<|eot_id|>"),
            "assistant": ("<|start_header_id|>assistant<|end_header_id|>\n\n", "<|eot_id|>"),
            "tool": ("<|start_header_id|>ipython<|end_header_id|>\n\n", "<|eot_id|>"),
        },
        generation="<|start_header_id|>assistant<|end_header_id|>\n\n",
    ),
    "mistral": ChatTemplate(
        prefix="",
        roles={
            "user": ("[INST] ", " [/INST]"),
            "assistant": (" ", "</s>"),
            "tool": ("[TOOL_RESULTS] ", " [/TOOL_RESULTS]"),
        },
        # The prompt ends on `[/INST]`, which is itself the invitation to answer.
        generation="",
        merge_system=True,
    ),
    "zephyr": ChatTemplate(
        prefix="",
        roles={
            "system": ("<|system|>\n", "</s>\n"),
            "user": ("<|user|>\n", "</s>\n"),
            "assistant": ("<|assistant|>\n", "</s>\n"),
            "tool": ("<|tool|>\n", "</s>\n"),
        },
        generation="<|assistant|>\n",
    ),
}


def parse_tool_calls(text: str) -> tuple[ToolCall, ...]:
    """The calls a completions response asked for, in the order it wrote them.

    A block whose JSON the model mangled is not a call and is left as prose.
    """
    calls = []
    for block in TOOL_CALL_BLOCK.findall(text):
        call = _decode(block)
        if call is not None and "name" in call:
            calls.append(ToolCall(str(call["name"]), parse_arguments(call.get("arguments"))))
    return tuple(calls)


def _tool_instructions(tools: Sequence[Tool]) -> str:
    """The system turn text describing the tools and how to call them."""
    definitions = "\n".join(json.dumps(tool.definition["function"]) for tool in tools)
    return f"You have access to the following tools:\n\n{definitions}\n\n{_CALL_FORMAT}"


def _with_tools(messages: list[dict], tools: Sequence[Tool]) -> list[dict]:
    """Append the tool instructions to the system turn, adding one if there is none."""
    if not tools:
        return messages
    instructions = _tool_instructions(tools)
    if messages[0]["role"] != "system":
        return [{"role": "system", "content": instructions}, *messages]
    head = messages[0]
    return [{**head, "content": f"{head['content']}\n\n{instructions}"}, *messages[1:]]


def _folded(messages: list[dict]) -> list[dict]:
    """Fold a leading system turn into the user turn that follows it."""
    if messages[0]["role"] != "system":
        return messages
    system, user, *rest = messages
    return [{**user, "content": f"{system['content']}\n\n{user['content']}"}, *rest]


def _content(message: dict) -> str:
    """The text of one turn; a tool result is tagged so the model can attribute it."""
    if message["role"] != "tool":
        return message["content"]
    result = json.dumps({"name": message["name"], "content": message["content"]})
    return f"<tool_response>\n{result}\n</tool_response>"


def _decode(block: str) -> dict | None:
    try:
        parsed = json.loads(block)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None

