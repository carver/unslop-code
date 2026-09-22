"""Tools an agentic task may call, and the handlers that answer them.

A tool is a name, a description and a JSON-schema parameter object — the
three fields an OpenAI-compatible `tools` entry needs — plus a handler that
turns the parsed arguments into the string fed back to the model.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .errors import ConfigError

HANDLER_TYPES = ("echo", "static_map", "script")
MISSING_VALUE = "NOT_FOUND"
SCRIPT_TIMEOUT_SECONDS = 10.0

EMPTY_PARAMETERS = {"type": "object", "properties": {}}


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation the model asked for, with its arguments parsed."""

    id: str | None
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolInvocation:
    """One executed tool call, as `result.tool_calls` records it."""

    iteration: int
    tool: str
    args: dict[str, Any]
    result: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
        }


class EchoHandler:
    """Hands the parsed arguments straight back to the model."""

    async def run(self, arguments: Mapping[str, Any]) -> str:
        return json.dumps(dict(arguments))


@dataclass(frozen=True)
class StaticMapHandler:
    """Answers from a fixed table keyed on the tool's first required parameter."""

    key: str
    mapping: Mapping[str, str]
    default: str

    async def run(self, arguments: Mapping[str, Any]) -> str:
        return self.mapping.get(str(arguments.get(self.key)), self.default)


@dataclass(frozen=True)
class ScriptHandler:
    """Runs `command` with one argument and answers with its stdout."""

    command: tuple[str, ...]
    arg_field: str
    timeout: float

    async def run(self, arguments: Mapping[str, Any]) -> str:
        process = await asyncio.create_subprocess_exec(
            *self.command,
            str(arguments.get(self.arg_field, "")),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), self.timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return f"ERROR: timed out after {self.timeout}s"
        if process.returncode != 0:
            return f"ERROR: {stderr.decode().strip()}"
        return stdout.decode().strip()


@dataclass(frozen=True)
class ToolConfig:
    """One declared tool: its model-facing schema and its handler."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Any

    def as_request_tool(self) -> dict[str, Any]:
        """The OpenAI `tools` entry sent in chat mode."""
        return {"type": "function", "function": self.schema()}

    def schema(self) -> dict[str, Any]:
        """The bare function definition, also used to describe the tool in text."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def build_tools(raw: Any, where: str) -> tuple[ToolConfig, ...]:
    """Validate a task's `tools` list; an absent list means no tools."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"{where}.tools must be a list of tool definitions")
    return tuple(
        _build_tool(tool, f"{where}.tools[{index}]") for index, tool in enumerate(raw)
    )


def _build_tool(raw: Any, where: str) -> ToolConfig:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where} must be a mapping")
    name = raw.get("name")
    if not name:
        raise ConfigError(f"{where}.name is required")
    parameters = raw.get("parameters") or EMPTY_PARAMETERS
    if not isinstance(parameters, Mapping):
        raise ConfigError(f"{where}.parameters must be a JSON schema object")
    return ToolConfig(
        name=str(name),
        description=str(raw.get("description", "")),
        parameters=dict(parameters),
        handler=_build_handler(raw.get("handler"), parameters, where),
    )


def _build_handler(raw: Any, parameters: Mapping[str, Any], where: str) -> Any:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where}.handler must be a mapping with a 'type'")
    kind = raw.get("type")
    if kind not in HANDLER_TYPES:
        raise ConfigError(
            f"{where}.handler.type must be one of {', '.join(HANDLER_TYPES)}, got '{kind}'"
        )
    if kind == "echo":
        return EchoHandler()
    if kind == "static_map":
        return _static_map(raw, parameters, where)
    return _script(raw, where)


def _static_map(raw: Mapping[str, Any], parameters: Mapping[str, Any], where: str):
    mapping = raw.get("mapping") or {}
    if not isinstance(mapping, Mapping):
        raise ConfigError(f"{where}.handler.mapping must be a mapping")
    return StaticMapHandler(
        key=_lookup_key(parameters, where),
        mapping={str(key): str(value) for key, value in mapping.items()},
        default=str(raw.get("default", MISSING_VALUE)),
    )


def _lookup_key(parameters: Mapping[str, Any], where: str) -> str:
    """The first required parameter, which `static_map` looks its answer up by."""
    required = parameters.get("required") or list(parameters.get("properties") or ())
    if not required:
        raise ConfigError(f"{where}.parameters needs a required parameter for 'static_map'")
    return str(required[0])


def _script(raw: Mapping[str, Any], where: str) -> ScriptHandler:
    command = raw.get("command")
    arg_field = raw.get("arg_field")
    if not command or not arg_field:
        raise ConfigError(f"{where}.handler needs 'command' and 'arg_field' for 'script'")
    return ScriptHandler(
        command=tuple(shlex.split(str(command))),
        arg_field=str(arg_field),
        timeout=float(raw.get("timeout", SCRIPT_TIMEOUT_SECONDS)),
    )


async def execute_calls(
    tools: Sequence[ToolConfig], calls: Sequence[ToolCall], iteration: int
) -> list[ToolInvocation]:
    """Run every call of one iteration, in the order the model asked for them."""
    handlers = {tool.name: tool.handler for tool in tools}
    invocations = []
    for call in calls:
        handler = handlers.get(call.name)
        result = (
            await handler.run(call.arguments)
            if handler
            else f"ERROR: unknown tool '{call.name}'"
        )
        invocations.append(ToolInvocation(iteration, call.name, call.arguments, result))
    return invocations
