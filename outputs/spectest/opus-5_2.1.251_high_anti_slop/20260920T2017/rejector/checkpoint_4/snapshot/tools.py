"""The tools an agentic task may call, and the handlers that answer them.

A tool is a name, the JSON schema the model is shown, and a handler that turns
the arguments the model supplied into the string fed back into the conversation.
Handlers are deliberately small: they stand in for real services during a run.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass
from typing import Any, Protocol

HANDLER_TYPES = ("echo", "static_map", "script")
#: What a `static_map` handler answers with when its `default` is not configured.
DEFAULT_TOOL_RESULT = "NOT_FOUND"
SCRIPT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class ToolCall:
    """One invocation the model asked for, with its arguments already parsed."""

    id: str
    name: str
    arguments: dict[str, Any]

    def as_message(self) -> dict[str, Any]:
        """The `tool_calls` entry that replays this call back to the model."""
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }


class ToolHandler(Protocol):
    """What a tool does with the arguments the model supplied."""

    async def run(self, arguments: dict[str, Any]) -> str: ...


@dataclass(frozen=True)
class EchoHandler:
    """Hands the parsed arguments straight back, as a JSON string."""

    async def run(self, arguments: dict[str, Any]) -> str:
        return json.dumps(arguments)


@dataclass(frozen=True)
class StaticMapHandler:
    """Looks the tool's first required parameter up in a fixed table."""

    key_field: str
    mapping: dict[str, Any]
    default: str

    async def run(self, arguments: dict[str, Any]) -> str:
        return str(self.mapping.get(arguments.get(self.key_field), self.default))


@dataclass(frozen=True)
class ScriptHandler:
    """Runs `command` with the value of `arg_field` as its single argument.

    The command's stdout is the tool's result; a failure or a hang is reported
    to the model as an `ERROR:` line rather than ending the run, so it can try
    something else on the next iteration.
    """

    command: str
    arg_field: str

    async def run(self, arguments: dict[str, Any]) -> str:
        process = await asyncio.create_subprocess_exec(
            *shlex.split(self.command),
            str(arguments.get(self.arg_field, "")),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=SCRIPT_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return f"ERROR: timed out after {SCRIPT_TIMEOUT_SECONDS:g}s"
        if process.returncode != 0:
            return f"ERROR: {stderr.decode().strip()}"
        return stdout.decode()


@dataclass(frozen=True)
class ToolConfig:
    """One tool: what the model is told about it, and what runs when it calls."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    @property
    def definition(self) -> dict[str, Any]:
        """The entry a chat request sends in its `tools` array."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


async def invoke(tools: tuple[ToolConfig, ...], call: ToolCall) -> str:
    """Run the tool the call names, or tell the model there is no such tool."""
    for tool in tools:
        if tool.name == call.name:
            return await tool.handler.run(call.arguments)
    return f"ERROR: unknown tool '{call.name}'"
