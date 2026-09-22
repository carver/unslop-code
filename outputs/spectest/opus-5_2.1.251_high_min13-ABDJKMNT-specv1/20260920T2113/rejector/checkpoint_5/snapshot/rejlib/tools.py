"""The tools an agentic task exposes, and the handlers that answer them."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
from dataclasses import dataclass, field

from rejlib.errors import ConfigError
from rejlib.validate import choice, mapping, required_text, submapping

HANDLER_TYPES = ("echo", "static_map", "script")

#: "`default`, which defaults to `"NOT_FOUND"`"
DEFAULT_MISSING = "NOT_FOUND"

#: A `script` handler that outlives this budget is killed and reports an error (T61).
SCRIPT_TIMEOUT_SECONDS = 10.0

#: The block a completions-mode model emits to ask for a tool.
CALL_BLOCK = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


@dataclass(frozen=True)
class Handler:
    """How one tool turns arguments into a result string."""

    type: str
    #: `static_map`: the lookup table and the value for a key it does not hold.
    mapping: dict[str, str] = field(default_factory=dict)
    default: str = DEFAULT_MISSING
    #: `script`: the command to run and the argument that is passed to it.
    command: str | None = None
    arg_field: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    """One tool definition: what the model is told, and what serves the call."""

    name: str
    description: str
    parameters: dict
    handler: Handler

    @property
    def key_field(self) -> str | None:
        """The first required parameter, which `static_map` looks up (T59)."""
        required = self.parameters.get("required")
        return required[0] if isinstance(required, list) and required else None

    @property
    def definition(self) -> dict:
        """This tool in the OpenAI `tools` shape."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class Invocation:
    """One tool call a model response asked for."""

    #: The call id chat mode ties the result message to; ``None`` in completions mode.
    id: str | None
    name: str
    args: dict


def load_tools(raw, label: str) -> tuple[ToolSpec, ...]:
    """Build a task's tool list, or an empty one when it declares no tools."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"{label} must be a list of tool definitions")
    return tuple(_tool(entry, f"{label}[{index}]") for index, entry in enumerate(raw))


def definitions(tools: tuple[ToolSpec, ...]) -> list[dict]:
    """The `tools` array a chat request carries."""
    return [tool.definition for tool in tools]


def tool_prompt(tools: tuple[ToolSpec, ...]) -> str:
    """The tools section a completions prompt carries instead of a `tools` field (T66)."""
    listing = "\n".join(
        json.dumps({"name": tool.name, "description": tool.description,
                    "parameters": tool.parameters})
        for tool in tools
    )
    return (
        "You have access to the following tools:\n"
        f"{listing}\n\n"
        "To call a tool, reply with a block of the form:\n"
        "<tool_call>\n"
        '{"name": "<tool name>", "arguments": {<arguments>}}\n'
        "</tool_call>\n"
        "When you need no further tool results, reply with your final answer instead."
    )


def parse_calls(api_type: str, message: dict) -> list[Invocation]:
    """The tool calls one assistant message asks for, in the order it lists them."""
    return _PARSERS[api_type](message)


async def run_tool(tools: tuple[ToolSpec, ...], name: str, args: dict) -> str:
    """Run the named tool's handler; a tool the task never declared is an error (T62)."""
    tool = next((candidate for candidate in tools if candidate.name == name), None)
    if tool is None:
        return f"ERROR: unknown tool '{name}'"
    return await _HANDLERS[tool.handler.type](tool, args)


def _tool(raw, label: str) -> ToolSpec:
    body = mapping(raw, label)
    return ToolSpec(
        name=required_text(body, "name", f"{label}.name"),
        description=body.get("description", ""),
        parameters=submapping(body, "parameters", f"{label}.parameters"),
        handler=_handler(body.get("handler"), f"{label}.handler"),
    )


def _handler(raw, label: str) -> Handler:
    body = mapping(raw, label)
    kind = choice(f"{label}.type", body.get("type"), HANDLER_TYPES)
    return _LOADERS[kind](body, label)


def _static_map_handler(body: dict, label: str) -> Handler:
    entries = mapping(body.get("mapping"), f"{label}.mapping")
    return Handler(
        type="static_map",
        mapping={str(key): str(value) for key, value in entries.items()},
        default=str(body.get("default", DEFAULT_MISSING)),
    )


def _script_handler(body: dict, label: str) -> Handler:
    return Handler(
        type="script",
        command=required_text(body, "command", f"{label}.command"),
        arg_field=required_text(body, "arg_field", f"{label}.arg_field"),
    )


_LOADERS = {
    "echo": lambda body, label: Handler(type="echo"),
    "static_map": _static_map_handler,
    "script": _script_handler,
}


async def _echo(tool: ToolSpec, args: dict) -> str:
    """Hand the parsed tool arguments back to the model as a JSON string."""
    return json.dumps(args)


async def _static_map(tool: ToolSpec, args: dict) -> str:
    """Look up the first required parameter in the mapping, else the default."""
    handler = tool.handler
    key = tool.key_field or next(iter(args), None)
    return handler.mapping.get(str(args.get(key)), handler.default)


async def _script(tool: ToolSpec, args: dict) -> str:
    """Run the command with one argument and return its stdout, stripped (T60)."""
    handler = tool.handler
    if handler.arg_field not in args:
        return f"ERROR: missing argument '{handler.arg_field}'"

    process = await asyncio.create_subprocess_exec(
        *shlex.split(handler.command), str(args[handler.arg_field]),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=SCRIPT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return f"ERROR: timeout after {SCRIPT_TIMEOUT_SECONDS:g}s"

    if process.returncode != 0:
        return f"ERROR: {stderr.decode().strip()}"
    return stdout.decode().strip()


_HANDLERS = {"echo": _echo, "static_map": _static_map, "script": _script}


def _chat_calls(message: dict) -> list[Invocation]:
    """Tool calls in the OpenAI `tool_calls` array."""
    return [
        Invocation(call.get("id"), call["function"]["name"],
                   _arguments(call["function"].get("arguments")))
        for call in message.get("tool_calls") or []
    ]


def _text_calls(message: dict) -> list[Invocation]:
    """Tool calls written as `<tool_call>` blocks in the response text."""
    calls = []
    for block in CALL_BLOCK.findall(message.get("content") or ""):
        parsed = _arguments(block)
        if parsed:
            calls.append(Invocation(None, parsed.get("name", ""),
                                    _arguments(parsed.get("arguments"))))
    return calls


_PARSERS = {"chat": _chat_calls, "completions": _text_calls}


def _arguments(raw) -> dict:
    """A JSON object from a string, a mapping, or nothing usable at all (T62).

    "parse `function.arguments` as JSON before invoking the handler" - chat mode
    sends them as a string, completions mode writes them inline.
    """
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
