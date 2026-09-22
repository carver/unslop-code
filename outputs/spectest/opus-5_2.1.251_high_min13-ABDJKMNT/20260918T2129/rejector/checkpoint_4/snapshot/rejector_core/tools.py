"""Tools an agentic task may call, and the handlers that answer them.

A tool couples an OpenAI-style function declaration, which is what the model
sees, with a local handler that turns parsed arguments into the string fed
back into the conversation as the tool result.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .errors import ConfigError

HANDLER_TYPES = ("echo", "static_map", "script")
DEFAULT_STATIC_RESULT = "NOT_FOUND"
SCRIPT_TIMEOUT_SECONDS = 10.0


class Handler(Protocol):
    """Produces a tool result from the arguments the model supplied."""

    async def invoke(self, args: dict) -> str: ...


@dataclass(frozen=True)
class EchoHandler:
    """Returns the parsed tool arguments as a JSON string."""

    async def invoke(self, args: dict) -> str:
        return json.dumps(args)


@dataclass(frozen=True)
class StaticMapHandler:
    """Looks the tool's first required parameter up in a fixed mapping."""

    mapping: dict
    default: str
    key_field: str | None

    async def invoke(self, args: dict) -> str:
        key = args.get(self.key_field) if self.key_field else next(iter(args.values()), None)
        return self.mapping.get(str(key), self.default)


@dataclass(frozen=True)
class ScriptHandler:
    """Runs `command` with one argument and returns what it printed."""

    command: str
    arg_field: str
    timeout: float

    async def invoke(self, args: dict) -> str:
        argv = [*shlex.split(self.command), str(args.get(self.arg_field, ""))]
        process = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            return f"ERROR: timed out after {self.timeout:g}s"

        if process.returncode != 0:
            return f"ERROR: {stderr.decode().strip()}"
        return stdout.decode().strip()


@dataclass(frozen=True)
class ToolSpec:
    """One declared tool."""

    name: str
    description: str
    parameters: dict
    handler: Handler

    @property
    def declaration(self) -> dict:
        """The tool as declared, which is also what a rendered prompt shows."""
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    @property
    def definition(self) -> dict:
        """The entry sent in a chat request's `tools` list."""
        return {"type": "function", "function": self.declaration}


def build_tools(raw, label: str) -> tuple[ToolSpec, ...]:
    """Validate a task's `tools` section."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"{label} must be a list")
    return tuple(_build_tool(entry, f"{label}[{index}]") for index, entry in enumerate(raw))


def describe_tools(tools: Sequence[ToolSpec]) -> str:
    """The prompt text declaring the tools of a completions-mode request.

    Completions requests have no native tools field, so the declarations and
    the call syntax the loop parses back out are spelled out in the prompt.
    """
    declarations = "\n".join(json.dumps(tool.declaration) for tool in tools)
    return (
        "You have access to the following tools:\n"
        f"{declarations}\n\n"
        "To call a tool, emit a block of the form:\n"
        "<tool_call>\n"
        '{"name": "<tool name>", "arguments": {<arguments>}}\n'
        "</tool_call>\n"
        "Otherwise reply with your final answer."
    )


def _build_tool(entry, label: str) -> ToolSpec:
    if not isinstance(entry, dict):
        raise ConfigError(f"{label} must be a mapping")

    name = entry.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{label}.name is required")

    parameters = entry.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ConfigError(f"{label}.parameters must be a mapping")

    return ToolSpec(
        name=name,
        description=str(entry.get("description", "")),
        parameters=parameters,
        handler=_build_handler(entry.get("handler"), parameters, f"{label}.handler"),
    )


def _build_handler(handler, parameters: dict, label: str) -> Handler:
    if not isinstance(handler, dict):
        raise ConfigError(f"{label} is required")

    kind = handler.get("type")
    if kind not in HANDLER_TYPES:
        raise ConfigError(
            f"unknown handler type '{kind}'; expected one of {', '.join(HANDLER_TYPES)}"
        )
    if kind == "echo":
        return EchoHandler()
    if kind == "static_map":
        return _static_map_handler(handler, parameters, label)
    return _script_handler(handler, label)


def _static_map_handler(handler: dict, parameters: dict, label: str) -> StaticMapHandler:
    mapping = handler.get("mapping")
    if not isinstance(mapping, dict):
        raise ConfigError(f"{label}.mapping is required for the static_map type")

    required = parameters.get("required") or []
    return StaticMapHandler(
        mapping={str(key): str(value) for key, value in mapping.items()},
        default=str(handler.get("default", DEFAULT_STATIC_RESULT)),
        key_field=required[0] if required else None,
    )


def _script_handler(handler: dict, label: str) -> ScriptHandler:
    for key in ("command", "arg_field"):
        if not isinstance(handler.get(key), str):
            raise ConfigError(f"{label}.{key} is required for the script type")

    timeout = handler.get("timeout", SCRIPT_TIMEOUT_SECONDS)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ConfigError(f"{label}.timeout must be a positive number")

    return ScriptHandler(
        command=handler["command"], arg_field=handler["arg_field"], timeout=float(timeout)
    )
