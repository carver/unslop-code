"""The tools an agentic task may call: definitions, calls and handlers.

A task declares its tools in the config; each one names the handler that answers
it. Models with native tool support ask for a call through the API's
`tool_calls` field, while `/v1/completions` models are taught the `<tool_call>`
text block instead — both arrive here as a `ToolCall` with parsed arguments.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any

from errors import RejectorError

ECHO = "echo"
STATIC_MAP = "static_map"
SCRIPT = "script"

#: What a `static_map` handler returns for a key it does not know and no `default` overrides.
MISSING_RESULT = "NOT_FOUND"
SCRIPT_TIMEOUT_SECONDS = 10.0

#: The tool call a model without native tool support writes into its response text.
TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

TOOL_INSTRUCTIONS = """You have access to the following tools:

{definitions}

To call a tool, reply with a block of exactly this form:
<tool_call>
{{"name": "<tool name>", "arguments": {{"<parameter>": "<value>"}}}}
</tool_call>

When you have the final answer, reply with it as plain text and no tool call."""


@dataclass(frozen=True)
class ToolCall:
    """One invocation a model asked for, with its arguments already parsed."""

    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Handler:
    """How a tool produces its result; the trailing fields belong to one handler type each."""

    type: str
    #: The argument read from the call: `arg_field` for a script, the first required parameter for a static map.
    arg_field: str | None = None
    mapping: dict[str, str] = field(default_factory=dict)
    default: str = MISSING_RESULT
    command: str | None = None


@dataclass(frozen=True)
class Tool:
    """One callable tool: what the model is told about it and what answers it."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler

    @property
    def definition(self) -> dict[str, Any]:
        """The tool as an OpenAI function definition."""
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


class Toolbox:
    """The tools one task offers, ready to be advertised to the model and invoked."""

    def __init__(self, tools: Sequence[Tool]) -> None:
        self.tools = tuple(tools)
        self._by_name = {tool.name: tool for tool in tools}

    async def invoke(self, call: ToolCall) -> str:
        """Run the handler of the named tool and return the text handed back to the model."""
        tool = self._by_name.get(call.name)
        if tool is None:
            return f"ERROR: unknown tool '{call.name}'"
        return await HANDLERS[tool.handler.type](tool.handler, call.args)


async def _echo(handler: Handler, args: dict[str, Any]) -> str:
    """Hand the parsed arguments straight back to the model."""
    return json.dumps(args)


async def _static_map(handler: Handler, args: dict[str, Any]) -> str:
    """Look the call's key argument up in the configured mapping."""
    return handler.mapping.get(str(args.get(handler.arg_field)), handler.default)


async def _script(handler: Handler, args: dict[str, Any]) -> str:
    """Run the configured command with the argument as its single parameter."""
    process = await asyncio.create_subprocess_exec(
        *shlex.split(handler.command),
        str(args.get(handler.arg_field, "")),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), SCRIPT_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return f"ERROR: timed out after {SCRIPT_TIMEOUT_SECONDS:g}s"

    if process.returncode != 0:
        return f"ERROR: {stderr.decode().strip()}"
    return stdout.decode().strip()


HANDLERS: dict[str, Callable[[Handler, dict[str, Any]], Coroutine[Any, Any, str]]] = {
    ECHO: _echo,
    STATIC_MAP: _static_map,
    SCRIPT: _script,
}


def describe(tools: Sequence[Tool]) -> str:
    """The prompt section teaching a completions model the tools and the call format."""
    definitions = "\n".join(json.dumps(tool.definition) for tool in tools)
    return TOOL_INSTRUCTIONS.format(definitions=definitions)


def parse_tool_calls(text: str) -> tuple[ToolCall, ...]:
    """The `<tool_call>` blocks of a response, in the order the model wrote them."""
    calls = []
    for index, match in enumerate(TOOL_CALL_BLOCK.finditer(text), start=1):
        block = _block(match.group(1))
        if block is not None:
            calls.append(ToolCall(id=f"call_{index}", name=str(block["name"]), args=block.get("arguments") or {}))
    return tuple(calls)


def _block(payload: str) -> dict[str, Any] | None:
    """The object inside one tool-call block, or None when the model wrote something unusable."""
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) and parsed.get("name") else None


def load_tools(raw: Any, prefix: str) -> tuple[Tool, ...]:
    """Validate a task's `tools` section; `prefix` names it in error messages."""
    if not isinstance(raw, list) or not raw:
        raise RejectorError(f"{prefix} must be a non-empty list")
    return tuple(_tool(entry, f"{prefix}[{index}]") for index, entry in enumerate(raw))


def _tool(entry: Any, prefix: str) -> Tool:
    if not isinstance(entry, dict) or not entry.get("name"):
        raise RejectorError(f"{prefix}.name is required")

    parameters = entry.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise RejectorError(f"{prefix}.parameters must be a mapping")

    return Tool(
        name=str(entry["name"]),
        description=str(entry.get("description", "")),
        parameters=parameters,
        handler=_handler(entry.get("handler"), parameters, f"{prefix}.handler"),
    )


def _handler(section: Any, parameters: dict[str, Any], prefix: str) -> Handler:
    """Validate one tool's handler section against the fields its type needs."""
    if not isinstance(section, dict) or section.get("type") not in HANDLERS:
        raise RejectorError(f"{prefix}.type must be one of {sorted(HANDLERS)}, got {_type_of(section)!r}")

    kind = section["type"]
    if kind == STATIC_MAP:
        return Handler(
            type=kind,
            arg_field=_lookup_field(parameters, prefix),
            mapping=_mapping(section.get("mapping"), prefix),
            default=str(section.get("default", MISSING_RESULT)),
        )
    if kind == SCRIPT:
        return Handler(
            type=kind,
            arg_field=_required(section, "arg_field", prefix),
            command=_required(section, "command", prefix),
        )
    return Handler(type=kind)


def _type_of(section: Any) -> Any:
    return section.get("type") if isinstance(section, dict) else section


def _lookup_field(parameters: dict[str, Any], prefix: str) -> str:
    """The parameter a static map looks up: the first one the tool declares as required."""
    required = parameters.get("required")
    if not isinstance(required, list) or not required:
        raise RejectorError(f"{prefix} of type '{STATIC_MAP}' needs the tool to declare a required parameter")
    return str(required[0])


def _mapping(mapping: Any, prefix: str) -> dict[str, str]:
    if not isinstance(mapping, dict) or not mapping:
        raise RejectorError(f"{prefix}.mapping must be a non-empty mapping for type '{STATIC_MAP}'")
    return {str(key): str(value) for key, value in mapping.items()}


def _required(section: dict[str, Any], key: str, prefix: str) -> str:
    if not section.get(key):
        raise RejectorError(f"{prefix}.{key} is required for type '{section['type']}'")
    return str(section[key])
