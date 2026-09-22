"""The tools an agentic task exposes and the handlers that answer their calls.

Parsing of the `tools` config section lives in `config.py`; this module owns the
shapes it produces and the execution of a single call.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from shell import COMMAND_TIMEOUT_SECONDS, run_program

HANDLER_TYPES = ("echo", "static_map", "script")
# What a `static_map` handler answers with when its mapping has no entry.
DEFAULT_TOOL_RESULT = "NOT_FOUND"


@dataclass(frozen=True)
class ToolCall:
    """One call the model asked for, with `arguments` already parsed out of JSON.

    `id` is the identifier the chat endpoint assigns so results can be matched
    back to their call; a call parsed out of completions text has none.
    """

    name: str
    arguments: dict
    id: str | None = None


@dataclass(frozen=True)
class Handler:
    """How a tool produces its result.

    Each field belongs to a subset of the types: `mapping` and `default` to
    `static_map`, `command` and `arg_field` to `script`.
    """

    type: str
    mapping: dict[str, str] = field(default_factory=dict)
    default: str = DEFAULT_TOOL_RESULT
    command: str | None = None
    arg_field: str | None = None


@dataclass(frozen=True)
class Tool:
    """A tool the model may call: its JSON schema and the handler behind it."""

    name: str
    description: str
    parameters: dict
    handler: Handler

    @property
    def required(self) -> list[str]:
        """The parameter names the schema marks as required."""
        return self.parameters.get("required", [])

    @property
    def definition(self) -> dict:
        """The tool as the chat endpoint's `tools` array wants it."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def parse_arguments(value: object) -> dict:
    """The arguments of a call as the model wrote them: an object, or a JSON string holding one.

    A model that mangles them is taken to have called with none, which its
    handler answers as usual rather than failing the row.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


async def call_tool(tools: dict[str, Tool], call: ToolCall) -> str:
    """Run one tool call and return the string the model sees as its result."""
    tool = tools.get(call.name)
    if tool is None:
        return f"ERROR: unknown tool '{call.name}'"
    return await _HANDLERS[tool.handler.type](tool, call.arguments)


async def _echo(tool: Tool, arguments: dict) -> str:
    """Hand the parsed arguments straight back, which is enough to stub a tool out."""
    return json.dumps(arguments)


async def _static_map(tool: Tool, arguments: dict) -> str:
    """Look the tool's first required argument up in the configured mapping."""
    key = next((arguments[name] for name in tool.required if name in arguments), None)
    return tool.handler.mapping.get(str(key), tool.handler.default)


async def _script(tool: Tool, arguments: dict) -> str:
    """Run the configured command with one argument, answering with its stdout."""
    handler = tool.handler
    argv = [*shlex.split(handler.command), str(arguments.get(handler.arg_field, ""))]
    code, stdout, stderr = await run_program(argv)
    if code is None:
        return f"ERROR: timed out after {COMMAND_TIMEOUT_SECONDS:.0f} seconds"
    if code != 0:
        return f"ERROR: {stderr.strip()}"
    return stdout.strip()


_HANDLERS: dict[str, Callable[[Tool, dict], Awaitable[str]]] = {
    "echo": _echo,
    "static_map": _static_map,
    "script": _script,
}
