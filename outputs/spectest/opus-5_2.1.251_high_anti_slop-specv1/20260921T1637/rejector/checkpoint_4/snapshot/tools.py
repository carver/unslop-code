"""Tools an agentic task may call: configuration, request rendering, and handlers.

A tool pairs a JSON-schema declaration the model sees with a handler that
answers a call locally, so a run never depends on a real tool backend.
"""

import asyncio
import json
import shlex
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from errors import ConfigError

HANDLER_TYPES = ("echo", "static_map", "script")
#: What ``static_map`` returns for an unmapped key when the tool sets no default.
DEFAULT_STATIC_RESULT = "NOT_FOUND"
#: A handler script still running after this long is reported as an error result.
SCRIPT_TIMEOUT_SECONDS = 10.0

#: Instructions describing the tools to a model that has no native tools field.
TOOL_PROMPT = """You have access to the following tools:

{definitions}

To call a tool, reply with one block per call and nothing else:
<tool_call>
{{"name": "<tool name>", "arguments": {{"<parameter>": "<value>"}}}}
</tool_call>

Results come back as <tool_response> blocks. Once you have everything you need,
reply with the final answer as plain text."""


@dataclass(frozen=True)
class HandlerConfig:
    """How a tool call is answered. Only the fields belonging to ``type`` are populated.

    ``mapping`` / ``default`` / ``key_field`` describe ``static_map``, and
    ``command`` / ``arg_field`` describe ``script``.
    """

    type: str
    mapping: Mapping[str, str] = field(default_factory=dict)
    default: str = DEFAULT_STATIC_RESULT
    key_field: str | None = None
    command: str | None = None
    arg_field: str | None = None


@dataclass(frozen=True)
class ToolConfig:
    """One tool: what the model is told about it, and what answers its calls."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: HandlerConfig


def build_tools(raw: Any, label: str) -> tuple[ToolConfig, ...]:
    """Validate the optional ``tools`` list that an agentic task calls during its loop."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{label}.tools must be a non-empty list")
    return tuple(_build_tool(tool, f"{label}.tools[{index}]") for index, tool in enumerate(raw))


def tool_definitions(tools: tuple[ToolConfig, ...]) -> list[dict[str, Any]]:
    """The tools as the ``tools`` field of a chat completions request."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


def tool_instructions(tools: tuple[ToolConfig, ...]) -> str:
    """The tools as prompt text, for completions requests that carry no ``tools`` field."""
    definitions = "\n".join(json.dumps(entry["function"]) for entry in tool_definitions(tools))
    return TOOL_PROMPT.format(definitions=definitions)


async def run_tool(tool: ToolConfig, args: Mapping[str, Any]) -> str:
    """Answer one tool call with the tool's configured handler."""
    return await _HANDLERS[tool.handler.type](tool.handler, args)


async def _echo(handler: HandlerConfig, args: Mapping[str, Any]) -> str:
    """Hand the parsed arguments straight back, which is enough to drive a loop."""
    return json.dumps(args)


async def _static_map(handler: HandlerConfig, args: Mapping[str, Any]) -> str:
    """Look the tool's first required parameter up in the configured table."""
    return handler.mapping.get(str(args.get(handler.key_field)), handler.default)


async def _script(handler: HandlerConfig, args: Mapping[str, Any]) -> str:
    """Run the configured command with one argument and report its stdout."""
    argv = [*shlex.split(handler.command), str(args.get(handler.arg_field, ""))]
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=SCRIPT_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        return f"ERROR: timed out after {SCRIPT_TIMEOUT_SECONDS:g}s"
    if process.returncode != 0:
        return f"ERROR: {stderr.decode().strip()}"
    return stdout.decode().strip()


def _build_tool(raw: Any, label: str) -> ToolConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} must be a mapping")
    parameters = raw.get("parameters")
    if not isinstance(parameters, dict):
        raise ConfigError(f"{label}.parameters must be a JSON schema mapping")
    return ToolConfig(
        name=_text(raw, "name", label),
        description=_text(raw, "description", label),
        parameters=parameters,
        handler=_build_handler(raw.get("handler"), parameters, f"{label}.handler"),
    )


def _build_handler(raw: Any, parameters: Mapping[str, Any], label: str) -> HandlerConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} must be a mapping")
    handler_type = raw.get("type")
    if handler_type not in HANDLER_TYPES:
        raise ConfigError(f"{label}.type must be one of: {', '.join(HANDLER_TYPES)}")
    extras = _TYPE_FIELDS.get(handler_type)
    return HandlerConfig(type=handler_type, **(extras(raw, parameters, label) if extras else {}))


def _static_map_fields(
    raw: Mapping[str, Any], parameters: Mapping[str, Any], label: str
) -> dict[str, Any]:
    """The ``static_map`` extras: the table, its fallback, and the parameter keyed on."""
    mapping = raw.get("mapping")
    if not isinstance(mapping, dict) or not mapping:
        raise ConfigError(f"{label}.mapping is required for 'static_map' handlers")
    required = parameters.get("required") or []
    if not required:
        raise ConfigError(f"{label}: 'static_map' needs a required parameter to look up")
    return {
        "mapping": {str(key): str(value) for key, value in mapping.items()},
        "default": str(raw.get("default", DEFAULT_STATIC_RESULT)),
        "key_field": str(required[0]),
    }


def _script_fields(
    raw: Mapping[str, Any], parameters: Mapping[str, Any], label: str
) -> dict[str, Any]:
    """The ``script`` extras: the command to run and the argument handed to it."""
    return {"command": _text(raw, "command", label), "arg_field": _text(raw, "arg_field", label)}


def _text(mapping: Mapping[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label}.{key} must be a non-empty string")
    return value


#: Per-type validators for the handler fields that only some types use.
_TYPE_FIELDS: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any], str], dict[str, Any]]] = {
    "static_map": _static_map_fields,
    "script": _script_fields,
}

#: Per-type handlers answering one tool call.
_HANDLERS: dict[str, Callable[[HandlerConfig, Mapping[str, Any]], Awaitable[str]]] = {
    "echo": _echo,
    "static_map": _static_map,
    "script": _script,
}
