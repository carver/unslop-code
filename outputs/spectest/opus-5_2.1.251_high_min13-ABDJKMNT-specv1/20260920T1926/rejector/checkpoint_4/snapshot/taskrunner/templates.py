"""Chat templates and the text tool-call protocol used in completions mode.

The completions endpoint takes one prompt string, so a conversation has to be
flattened. Three of the built-ins wrap every message in role markers and only
differ in which markers they use; `mistral` has no role markers at all and
folds system, user and tool turns into one `[INST]` block instead.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .tools import ToolCall, ToolConfig

TEMPLATES = ("chatml", "llama3", "mistral", "zephyr")

# What separates several turns that mistral has to fold into one block.
TURN_SEPARATOR = "\n\n"

# How the model is told to call a tool when no native `tools` field exists,
# and how its reply is read back.
TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

TOOL_INSTRUCTIONS = """You have access to the following tools:

{definitions}

To call a tool, reply with a block of the form:
<tool_call>
{{"name": "<tool name>", "arguments": {{"<parameter>": "<value>"}}}}
</tool_call>

Call as many tools as you need, then reply with your final answer as plain
text and no tool call blocks."""


@dataclass(frozen=True)
class MarkerTemplate:
    """A template that wraps each message in markers naming its role.

    `prefix` is formatted with the message's role, so a multi-turn
    conversation repeats the markers per message on its own; the same prefix
    with the `assistant` role ends the prompt and cues the reply.
    """

    prefix: str
    suffix: str
    header: str = ""

    def render(self, messages: Sequence[Mapping[str, Any]]) -> str:
        turns = "".join(
            self.prefix.format(role=message["role"]) + (message.get("content") or "")
            + self.suffix
            for message in messages
        )
        return self.header + turns + self.prefix.format(role="assistant")


def _render_mistral(messages: Sequence[Mapping[str, Any]]) -> str:
    """Instruction blocks closed by assistant turns, with no role markers.

    Mistral has no marker for anything but the instruction, so system, user
    and tool-result turns accumulate into the block that an assistant turn —
    or the end of the conversation — closes.
    """
    rendered, pending = [], []
    for message in messages:
        content = message.get("content") or ""
        if message["role"] == "assistant":
            rendered.append(f"[INST] {TURN_SEPARATOR.join(pending)} [/INST] {content}</s>")
            pending = []
        else:
            pending.append(content)
    return "".join(rendered) + f"[INST] {TURN_SEPARATOR.join(pending)} [/INST]"


_TEMPLATES = {
    "chatml": MarkerTemplate(prefix="<|im_start|>{role}\n", suffix="<|im_end|>\n"),
    "llama3": MarkerTemplate(
        prefix="<|start_header_id|>{role}<|end_header_id|>\n\n",
        suffix="<|eot_id|>",
        header="<|begin_of_text|>",
    ),
    "zephyr": MarkerTemplate(prefix="<|{role}|>\n", suffix="</s>\n"),
}


def render_prompt(template: str, messages: Sequence[Mapping[str, Any]]) -> str:
    """Flatten a conversation into the prompt string one template describes."""
    if template == "mistral":
        return _render_mistral(messages)
    return _TEMPLATES[template].render(messages)


def with_tool_instructions(
    messages: Sequence[Mapping[str, Any]], tools: Sequence[ToolConfig]
) -> list[dict[str, Any]]:
    """Describe the tools in the system turn, since there is no `tools` field."""
    if not tools:
        return list(messages)
    block = TOOL_INSTRUCTIONS.format(
        definitions="\n".join(json.dumps(tool.schema()) for tool in tools)
    )
    head, *rest = messages or [{"role": "system", "content": ""}]
    if head["role"] != "system":
        return [{"role": "system", "content": block}, *messages]
    joined = f"{head['content']}\n\n{block}" if head["content"] else block
    return [{"role": "system", "content": joined}, *rest]


def parse_tool_calls(text: str) -> tuple[ToolCall, ...]:
    """Read `<tool_call>` blocks out of a completion; malformed blocks are text."""
    calls = []
    for match in TOOL_CALL_BLOCK.finditer(text):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        calls.append(
            ToolCall(id=None, name=payload.get("name"), arguments=payload.get("arguments") or {})
        )
    return tuple(calls)
