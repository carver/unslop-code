"""Tool definitions for agentic tasks, their handlers, and their call shapes.

A task's `tools` block is validated into `ToolDefinition`s while the config
loads, so a bad handler stops the run before any API request. At run time the
agentic loop only has to parse the calls a response carries and invoke the
handler each one names.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import signal
from dataclasses import dataclass, field

from .errors import ConfigError

HANDLER_TYPES = ("echo", "static_map", "script")
DEFAULT_MISS = "NOT_FOUND"
SCRIPT_TIMEOUT_SECONDS = 10

TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
TOOL_PROMPT = (
    "You have access to the following tools:\n{tools}\n"
    "To call a tool, reply with one block per call, of the form:\n"
    "<tool_call>\n"
    '{{"name": "<tool name>", "arguments": {{<arguments>}}}}\n'
    "</tool_call>"
)


@dataclass(frozen=True)
class Handler:
    """What a tool does with the arguments a model sent it."""

    type: str
    mapping: dict = field(default_factory=dict)
    default: str = DEFAULT_MISS
    command: str = ""
    arg_field: str = ""


@dataclass(frozen=True)
class ToolDefinition:
    """One tool a task offers, and the parameters it advertises."""

    name: str
    description: str
    parameters: dict
    handler: Handler
    key_field: str | None

    @property
    def schema(self) -> dict:
        """The OpenAI function shape sent in a chat request's `tools` field."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolCall:
    """One call a model asked for, with its arguments already decoded."""

    id: str | None
    name: str
    args: dict


def build_tools(raw) -> tuple[ToolDefinition, ...]:
    """Validate a task's `tools` list into the definitions the loop uses."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("task.tools must be a list of tools")
    return tuple(_build_tool(tool) for tool in raw)


def find_tool(tools: tuple[ToolDefinition, ...], name: str) -> ToolDefinition | None:
    """The tool a call names, or None when the model invented one."""
    return next((tool for tool in tools if tool.name == name), None)


async def invoke_tool(tool: ToolDefinition, args: dict) -> str:
    """Run one tool's handler over the arguments the model supplied."""
    handler = tool.handler
    if handler.type == "script":
        return await _run_script(handler, args)
    if handler.type == "static_map":
        return str(handler.mapping.get(str(args.get(tool.key_field)), handler.default))
    return json.dumps(args)


def message_tool_calls(message: dict) -> tuple[ToolCall, ...]:
    """The calls carried by an OpenAI assistant message."""
    return tuple(
        ToolCall(
            id=call.get("id"),
            name=call["function"]["name"],
            args=_decode_args(call["function"].get("arguments")),
        )
        for call in message.get("tool_calls") or []
    )


def text_tool_calls(text: str) -> tuple[ToolCall, ...]:
    """The calls a completions-mode response wrote as `<tool_call>` blocks."""
    blocks = (_decode_block(block) for block in TOOL_CALL_PATTERN.findall(text or ""))
    return tuple(
        ToolCall(id=None, name=block["name"], args=_decode_args(block.get("arguments")))
        for block in blocks
        if isinstance(block, dict) and isinstance(block.get("name"), str)
    )


def with_tool_section(messages: list[dict], tools: tuple[ToolDefinition, ...]) -> list[dict]:
    """Describe `tools` in the system message, for prompts with no tools field."""
    section = TOOL_PROMPT.format(
        tools="\n".join(json.dumps(tool.schema["function"]) for tool in tools)
    )
    if messages and messages[0]["role"] == "system":
        head = {**messages[0], "content": f"{messages[0]['content']}\n\n{section}"}
        return [head, *messages[1:]]
    return [{"role": "system", "content": section}, *messages]


def _build_tool(raw) -> ToolDefinition:
    """Validate one entry of the `tools` list."""
    if not isinstance(raw, dict):
        raise ConfigError("each tool must be a mapping")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError("each tool requires a non-empty 'name'")

    parameters = raw.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ConfigError(f"tool {name!r}: 'parameters' must be a mapping")
    return ToolDefinition(
        name=name,
        description=str(raw.get("description", "")),
        parameters=parameters,
        handler=_build_handler(raw.get("handler"), name),
        key_field=_key_field(parameters),
    )


def _build_handler(raw, name: str) -> Handler:
    """Validate a tool's handler block, which decides how calls are answered."""
    if not isinstance(raw, dict):
        raise ConfigError(f"tool {name!r}: 'handler' must be a mapping")
    handler_type = raw.get("type")
    if handler_type not in HANDLER_TYPES:
        raise ConfigError(
            f"tool {name!r}: handler.type must be one of {', '.join(HANDLER_TYPES)}, "
            f"got {handler_type!r}"
        )
    if handler_type == "static_map":
        return _static_map_handler(raw, name)
    if handler_type == "script":
        return _script_handler(raw, name)
    return Handler(type=handler_type)


def _static_map_handler(raw: dict, name: str) -> Handler:
    mapping = raw.get("mapping")
    if not isinstance(mapping, dict):
        raise ConfigError(f"tool {name!r}: handler.mapping must be a mapping")
    return Handler(
        type="static_map",
        mapping={str(key): value for key, value in mapping.items()},
        default=str(raw.get("default", DEFAULT_MISS)),
    )


def _script_handler(raw: dict, name: str) -> Handler:
    command = raw.get("command")
    arg_field = raw.get("arg_field")
    if not isinstance(command, str) or not command:
        raise ConfigError(f"tool {name!r}: handler.command is required for 'script'")
    if not isinstance(arg_field, str) or not arg_field:
        raise ConfigError(f"tool {name!r}: handler.arg_field is required for 'script'")
    return Handler(type="script", command=command, arg_field=arg_field)


def _key_field(parameters: dict) -> str | None:
    """The first required parameter, which `static_map` looks up."""
    required = parameters.get("required")
    if isinstance(required, list) and required:
        return str(required[0])
    properties = parameters.get("properties")
    return next(iter(properties), None) if isinstance(properties, dict) else None


async def _run_script(handler: Handler, args: dict) -> str:
    """Run the handler's command over one argument and return its stdout.

    The command runs in its own session so a timeout kills the whole pipeline
    rather than leaving it behind the run.
    """
    process = await asyncio.create_subprocess_exec(
        *shlex.split(handler.command),
        str(args.get(handler.arg_field, "")),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), SCRIPT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        return f"ERROR: command timed out after {SCRIPT_TIMEOUT_SECONDS}s"

    if process.returncode != 0:
        return f"ERROR: {stderr.decode().strip()}"
    return stdout.decode().strip()


def _decode_args(value) -> dict:
    """Arguments as a decoded object, whether sent as JSON text or inline."""
    if isinstance(value, dict):
        return value
    decoded = _decode_block(value or "{}")
    return decoded if isinstance(decoded, dict) else {}


def _decode_block(text: str):
    """Decode model-written JSON, which is not guaranteed to be well formed."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
