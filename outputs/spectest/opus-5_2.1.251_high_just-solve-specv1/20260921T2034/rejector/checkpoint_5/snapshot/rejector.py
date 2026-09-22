#!/usr/bin/env python3
"""rejector - run YAML-configured prompt tasks against an OpenAI-compatible API.

Usage:
    python rejector.py run --config <path> --input <path> --output <path> [options]
    python rejector.py run --config <multi.yaml> --input <task>=<path> ... --output <dir>
    python rejector.py run --config <multi.yaml> --input-dir <dir> --output <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import os
import random
import re
import shlex
import signal
import sys
import time
from collections import deque
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import aiohttp
import yaml

EXIT_OK = 0
EXIT_ERROR = 1

SCHEMES = ("greedy", "sample", "rejection", "agentic")
API_TYPES = ("chat", "completions")
CHAT_TEMPLATES = ("chatml", "llama3", "mistral", "zephyr")
HANDLER_TYPES = ("echo", "static_map", "script")
ICL_STRATEGIES = ("fixed", "random", "round_robin")
EVAL_TYPES = ("exact_match", "contains", "regex", "llm_judge", "script")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")

MAX_HTTP_TRIES = 3  # total requests per logical attempt, including the first

SCRIPT_TIMEOUT = 10.0  # seconds; a timeout is a failed evaluation
TOOL_TIMEOUT = 10.0  # seconds; a script handler that overruns returns ERROR:
DEFAULT_MAX_ITERATIONS = 10  # agentic API requests allowed per loop
DEFAULT_STATIC_MAP_MISS = "NOT_FOUND"
RESPONSE_KEY = "__response__"
WORDS_PER_TOKEN = 0.75  # 1 token ~= 0.75 words when estimating a prompt
DRY_RUN_TOKENS_PER_WORD = 1.33  # dry-run prompt estimate
RATE_WINDOW = 60.0  # seconds; sliding window for both RPM and TPM
PROGRESS_INTERVAL = 5.0  # seconds between progress lines
PROGRESS_FRACTION = 0.10  # or every 10% of the inputs, whichever is first
DEFAULT_CONCURRENCY = 64  # worker pool size when no rpm/max_concurrent given
RESPONSE_PLACEHOLDER = "{%s}" % RESPONSE_KEY

# Placeholder such as {question}. Deliberately narrow so that JSON braces or
# prose inside a prompt template are left untouched.
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# A <tool_call>{...}</tool_call> block in a completions-mode response.
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)

# Integers/decimals, preferring a comma-grouped form when one is present.
NUMBER_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?|-?\.\d+")

# Multiple-choice letters, most explicit form first.
LETTER_RES = [
    re.compile(
        r"(?i:answer|choice|option|letter)\b(?:\s+(?i:is|would\s+be))?"
        r"\s*[:=\-]?\s*[\(\[]?\s*([A-D])(?![A-Za-z0-9])"
    ),
    re.compile(r"[\(\[]\s*([A-D])\s*[\)\]]"),
    re.compile(r"(?<![A-Za-z0-9])([A-D])\s*[\)\].:,]"),
    re.compile(r"(?<![A-Za-z0-9])([A-D])(?![A-Za-z0-9])"),
]


class ConfigError(Exception):
    """Raised for any configuration or input problem (exit code 1)."""


class BudgetExceeded(Exception):
    """Raised instead of sending a request once the cost budget is reached."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def to_text(value: Any) -> str:
    """Render an arbitrary JSON value as text for prompts/comparisons."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def render_template(template: str, row: Dict[str, Any], row_index: int) -> str:
    """Substitute {field} placeholders from ``row``.

    Raises ConfigError naming the row index and the first missing field.
    """
    missing: List[str] = []

    def repl(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in row:
            missing.append(name)
            return match.group(0)
        return to_text(row[name])

    rendered = PLACEHOLDER_RE.sub(repl, template)
    if missing:
        raise ConfigError(
            "row %d: missing field %r referenced by prompt template"
            % (row_index, missing[0])
        )
    return rendered


def render_with_response(
    template: str, row: Dict[str, Any], row_index: int, response: str
) -> str:
    """Render a template that may reference row fields and ``__response__``.

    A row field can itself expand to text containing ``{__response__}``; that
    second-level placeholder is substituted after the row fields are expanded.
    """
    context = dict(row)
    context[RESPONSE_KEY] = response
    rendered = render_template(template, context, row_index)
    if RESPONSE_PLACEHOLDER in rendered:
        rendered = rendered.replace(RESPONSE_PLACEHOLDER, response)
    return rendered


def template_fields(template: str) -> List[str]:
    return list(dict.fromkeys(PLACEHOLDER_RE.findall(template or "")))


def row_template_fields(template: str) -> List[str]:
    """Template fields that must come from the input row."""
    return [name for name in template_fields(template) if name != RESPONSE_KEY]


def extract_value(text: str, method: str) -> Optional[str]:
    """Apply an extract method to a model response."""
    if method == "full":
        return text
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return None
    if method == "last_number":
        matches = NUMBER_RE.findall(text)
        if not matches:
            return None
        return matches[-1].replace(",", "")
    if method == "first_number":
        match = NUMBER_RE.search(text)
        if match is None:
            return None
        return match.group(0).replace(",", "")
    if method == "letter":
        for pattern in LETTER_RES:
            match = pattern.search(text)
            if match is not None:
                return match.group(1)
        return None
    raise ConfigError("unknown extract method: %r" % (method,))


def _normalize(value: str) -> str:
    out = value.strip()
    out = out.replace(",", "")
    out = out.lstrip("$").strip()
    out = out.rstrip(".").strip()
    return out


def _as_float(value: str) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def answers_match(extracted: str, expected: str) -> bool:
    if extracted == expected:
        return True
    left, right = _normalize(extracted), _normalize(expected)
    if left == right:
        return True
    left_num, right_num = _as_float(left), _as_float(right)
    if left_num is not None and right_num is not None:
        return math.isclose(left_num, right_num, rel_tol=1e-9, abs_tol=1e-9)
    return left.casefold() == right.casefold()


def _to_score(extracted: Optional[str]) -> Optional[float]:
    if extracted is None:
        return None
    number = _as_float(_normalize(extracted))
    if number is None:
        found = NUMBER_RE.search(extracted)
        if found is None:
            return None
        number = _as_float(found.group(0).replace(",", ""))
    return number


def _json_number(value: Optional[float]) -> Optional[Any]:
    if value is None:
        return None
    if float(value).is_integer():
        return int(value)
    return value


# --------------------------------------------------------------------------- #
# Tools (agentic generation)
# --------------------------------------------------------------------------- #


class ToolDef:
    """One callable tool: an OpenAI-style declaration plus a local handler."""

    def __init__(
        self,
        name: str,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        handler_type: str = "echo",
        mapping: Optional[Dict[str, Any]] = None,
        default: str = DEFAULT_STATIC_MAP_MISS,
        command: Optional[str] = None,
        arg_field: Optional[str] = None,
        timeout: float = TOOL_TIMEOUT,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}
        self.handler_type = handler_type
        self.mapping = mapping or {}
        self.default = default
        self.command = command
        self.command_argv = shlex.split(command) if command else []
        self.arg_field = arg_field
        self.timeout = timeout

    def spec(self) -> Dict[str, Any]:
        """The OpenAI `tools` entry for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def primary_arg(self, args: Dict[str, Any]) -> Any:
        """The value of the first required parameter (with fallbacks)."""
        params = self.parameters if isinstance(self.parameters, dict) else {}
        required = params.get("required")
        if isinstance(required, list):
            for name in required:
                if isinstance(name, str) and name in args:
                    return args[name]
        properties = params.get("properties")
        if isinstance(properties, dict):
            for name in properties:
                if name in args:
                    return args[name]
        for value in args.values():
            return value
        return None

    async def run(self, args: Dict[str, Any]) -> str:
        """Execute the handler and return its result as text."""
        if not isinstance(args, dict):
            args = {}
        if self.handler_type == "echo":
            return json.dumps(args, ensure_ascii=False)
        if self.handler_type == "static_map":
            key = to_text(self.primary_arg(args))
            if key in self.mapping:
                return to_text(self.mapping[key])
            return self.default
        return await self._run_script(args)

    async def _run_script(self, args: Dict[str, Any]) -> str:
        """Run `command` with the arg_field value as one extra argument."""
        argv = list(self.command_argv) + [to_text(args.get(self.arg_field))]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # own group, so a timeout kills the tree
            )
        except OSError as exc:
            return "ERROR: %s" % exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            await _terminate(proc)
            return "ERROR: timeout after %g seconds" % self.timeout

        if proc.returncode != 0:
            message = stderr.decode("utf-8", "replace").strip()
            if not message:
                message = "exit code %s" % proc.returncode
            return "ERROR: %s" % message
        return stdout.decode("utf-8", "replace").strip()


def build_tools(raw: Any, label: str) -> List[ToolDef]:
    """Validate a task's `tools` list."""
    if not isinstance(raw, list) or not raw:
        raise ConfigError("%s must be a non-empty list" % label)

    tools: List[ToolDef] = []
    seen: Dict[str, int] = {}
    for position, item in enumerate(raw):
        tlabel = "%s[%d]" % (label, position)
        entry = _require_mapping(item, tlabel)

        name = entry.get("name")
        if name is None or not str(name).strip():
            raise ConfigError("%s.name is required" % tlabel)
        name = str(name).strip()
        if name in seen:
            raise ConfigError("%s.name %r is already defined" % (tlabel, name))
        seen[name] = position

        description = to_text(entry.get("description") or "")

        parameters_raw = entry.get("parameters")
        if parameters_raw is None:
            parameters: Dict[str, Any] = {"type": "object", "properties": {}}
        else:
            parameters = _require_mapping(parameters_raw, "%s.parameters" % tlabel)

        handler_raw = entry.get("handler")
        if handler_raw is None:
            raise ConfigError("%s.handler is required" % tlabel)
        handler = _require_mapping(handler_raw, "%s.handler" % tlabel)

        handler_type = handler.get("type")
        if handler_type is None or not str(handler_type).strip():
            raise ConfigError("%s.handler.type is required" % tlabel)
        handler_type = str(handler_type).strip()
        if handler_type not in HANDLER_TYPES:
            raise ConfigError(
                "%s.handler.type must be one of %s, got %r"
                % (tlabel, ", ".join(HANDLER_TYPES), handler_type)
            )

        mapping: Dict[str, Any] = {}
        default = DEFAULT_STATIC_MAP_MISS
        command: Optional[str] = None
        arg_field: Optional[str] = None
        timeout = TOOL_TIMEOUT

        if handler_type == "static_map":
            mapping_raw = handler.get("mapping")
            if mapping_raw is None:
                raise ConfigError(
                    "%s.handler.mapping is required for type 'static_map'" % tlabel
                )
            mapping_dict = _require_mapping(mapping_raw, "%s.handler.mapping" % tlabel)
            mapping = {to_text(key): value for key, value in mapping_dict.items()}
            if handler.get("default") is not None:
                default = to_text(handler["default"])
        elif handler_type == "script":
            command_raw = handler.get("command")
            if command_raw is None or not str(command_raw).strip():
                raise ConfigError(
                    "%s.handler.command is required for type 'script'" % tlabel
                )
            command = to_text(command_raw)
            arg_field_raw = handler.get("arg_field")
            if arg_field_raw is None or not str(arg_field_raw).strip():
                raise ConfigError(
                    "%s.handler.arg_field is required for type 'script'" % tlabel
                )
            arg_field = str(arg_field_raw).strip()
            if handler.get("timeout") is not None:
                timeout = _as_number(handler["timeout"], "%s.handler.timeout" % tlabel)
                if timeout <= 0:
                    raise ConfigError("%s.handler.timeout must be > 0" % tlabel)

        tools.append(
            ToolDef(
                name,
                description,
                parameters,
                handler_type,
                mapping=mapping,
                default=default,
                command=command,
                arg_field=arg_field,
                timeout=timeout,
            )
        )
    return tools


class ToolCall:
    """One tool invocation requested by the model."""

    def __init__(
        self,
        call_id: str,
        name: str,
        args: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        self.id = call_id
        self.name = name
        self.args = args if isinstance(args, dict) else {}
        self.error = error


def _decode_arguments(raw: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """Parse `function.arguments` (a JSON string, or an object already)."""
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, dict):
        return dict(raw), None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            return {}, "invalid tool arguments: %s" % exc
        if isinstance(parsed, dict):
            return parsed, None
        return {}, "tool arguments must be a JSON object"
    return {}, "tool arguments must be a JSON object"


def parse_message_tool_calls(message: Dict[str, Any]) -> List[ToolCall]:
    """Tool calls from a chat-mode assistant message."""
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    calls: List[ToolCall] = []
    for position, item in enumerate(raw_calls):
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        function = function if isinstance(function, dict) else {}
        name = function.get("name")
        args, error = _decode_arguments(function.get("arguments"))
        call_id = item.get("id") or "call_%d" % (position + 1)
        calls.append(ToolCall(str(call_id), str(name or ""), args, error))
    return calls


def parse_text_tool_calls(text: str) -> List[ToolCall]:
    """Tool calls from <tool_call>...</tool_call> blocks in raw text."""
    calls: List[ToolCall] = []
    for position, match in enumerate(TOOL_CALL_RE.finditer(text or "")):
        payload = match.group(1).strip()
        name = ""
        args: Dict[str, Any] = {}
        error: Optional[str] = None
        try:
            parsed = json.loads(payload)
        except ValueError as exc:
            parsed = None
            error = "invalid tool call: %s" % exc
        if isinstance(parsed, dict):
            name = str(parsed.get("name") or "")
            args, error = _decode_arguments(parsed.get("arguments"))
        elif parsed is not None:
            error = "tool call must be a JSON object"
        calls.append(ToolCall("call_%d" % (position + 1), name, args, error))
    return calls


def render_tool_call_block(call: ToolCall) -> str:
    """The textual form of a tool call, for completions-mode transcripts."""
    payload = json.dumps(
        {"name": call.name, "arguments": call.args}, ensure_ascii=False
    )
    return "<tool_call>\n%s\n</tool_call>" % payload


# --------------------------------------------------------------------------- #
# Chat templates (completions mode)
# --------------------------------------------------------------------------- #


def _message_text(message: Dict[str, Any]) -> str:
    """Flatten one conversation message into prompt text."""
    content = message.get("content")
    text = "" if content is None else to_text(content)
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        blocks = []
        for item in calls:
            if not isinstance(item, dict):
                continue
            function = item.get("function")
            function = function if isinstance(function, dict) else {}
            args, _error = _decode_arguments(function.get("arguments"))
            blocks.append(
                "<tool_call>\n%s\n</tool_call>"
                % json.dumps(
                    {"name": function.get("name") or "", "arguments": args},
                    ensure_ascii=False,
                )
            )
        rendered = "\n".join(blocks)
        text = "%s\n%s" % (text, rendered) if text else rendered
    return text


def _prepared_messages(
    messages: List[Dict[str, Any]], tools: Optional[List[ToolDef]] = None
) -> List[Tuple[str, str]]:
    """(role, text) pairs, with tool definitions folded into the system turn."""
    prepared: List[Tuple[str, str]] = [
        (str(message.get("role") or "user"), _message_text(message))
        for message in messages
    ]
    if not tools:
        return prepared

    section = render_tools_section(tools)
    for index, (role, text) in enumerate(prepared):
        if role == "system":
            joined = "%s\n\n%s" % (text, section) if text else section
            prepared[index] = (role, joined)
            return prepared
    return [("system", section)] + prepared


def render_tools_section(tools: List[ToolDef]) -> str:
    """Tool definitions rendered into the prompt for completions mode."""
    lines = ["You have access to the following tools:", ""]
    for tool in tools:
        lines.append(json.dumps(tool.spec()["function"], ensure_ascii=False))
    lines.extend(
        [
            "",
            "To call a tool, reply with one block per call:",
            "<tool_call>",
            '{"name": "<tool name>", "arguments": {<arguments>}}',
            "</tool_call>",
            "",
            "When you have the final answer, reply with plain text instead.",
        ]
    )
    return "\n".join(lines)


def _render_chatml(turns: List[Tuple[str, str]]) -> str:
    parts = ["<|im_start|>%s\n%s<|im_end|>\n" % (role, text) for role, text in turns]
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


def _render_llama3(turns: List[Tuple[str, str]]) -> str:
    parts = ["<|begin_of_text|>"]
    for role, text in turns:
        parts.append(
            "<|start_header_id|>%s<|end_header_id|>\n\n%s<|eot_id|>" % (role, text)
        )
    parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return "".join(parts)


def _render_zephyr(turns: List[Tuple[str, str]]) -> str:
    parts = ["<|%s|>\n%s</s>\n" % (role, text) for role, text in turns]
    parts.append("<|assistant|>\n")
    return "".join(parts)


def _render_mistral(turns: List[Tuple[str, str]]) -> str:
    """Mistral has no system/tool roles: they fold into the next [INST] block."""
    parts: List[str] = []
    pending: List[str] = []
    for role, text in turns:
        if role == "assistant":
            if pending:
                parts.append("[INST] %s [/INST]" % "\n\n".join(pending))
                pending = []
            parts.append(" %s</s>" % text)
            continue
        if role == "tool":
            pending.append("[TOOL_RESULTS] %s [/TOOL_RESULTS]" % text)
            continue
        if role == "system":
            pending.append(text)
            continue
        pending.append(text)
        parts.append("[INST] %s [/INST]" % "\n\n".join(pending))
        pending = []
    if pending or not parts or not parts[-1].endswith("[/INST]"):
        parts.append("[INST] %s [/INST]" % "\n\n".join(pending))
    return "".join(parts)


TEMPLATE_RENDERERS = {
    "chatml": _render_chatml,
    "llama3": _render_llama3,
    "mistral": _render_mistral,
    "zephyr": _render_zephyr,
}


def render_chat_prompt(
    template: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[ToolDef]] = None,
) -> str:
    """Render a conversation into a single completions-mode prompt string."""
    renderer = TEMPLATE_RENDERERS.get(template)
    if renderer is None:
        raise ConfigError("unknown chat template: %r" % (template,))
    return renderer(_prepared_messages(messages, tools))


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


class Evaluation:
    def __init__(
        self,
        type_: str,
        answer_field: Optional[str] = None,
        extract: Optional[str] = None,
        pattern: Optional[str] = None,
        judge_system: Optional[str] = None,
        judge_user: Optional[str] = None,
        threshold: Optional[float] = None,
        model: Optional[str] = None,
        command_template: Optional[str] = None,
        success_exit_code: int = 0,
    ) -> None:
        self.type = type_
        self.answer_field = answer_field
        self.extract = extract
        self.pattern_source = pattern
        self.pattern = re.compile(pattern) if pattern is not None else None
        self.judge_system = judge_system
        self.judge_user = judge_user
        self.threshold = threshold
        self.model = model
        self.command_template = command_template
        self.success_exit_code = success_exit_code

    def row_fields(self) -> List[str]:
        """Row fields the evaluation needs, beyond answer_field."""
        fields: List[str] = []
        for template in (self.judge_system, self.judge_user, self.command_template):
            if not template:
                continue
            for name in row_template_fields(template):
                if name not in fields:
                    fields.append(name)
        return fields

    def evaluate(self, text: str, row: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Return (passed, extracted_answer) for one response (sync types)."""
        if self.type == "exact_match":
            extracted = extract_value(text, self.extract or "full")
            expected = to_text(row.get(self.answer_field))
            passed = extracted is not None and answers_match(extracted, expected)
            return passed, extracted

        if self.type == "contains":
            expected = to_text(row.get(self.answer_field))
            passed = expected in text
            if self.extract:
                extracted = extract_value(text, self.extract)
            else:
                extracted = expected if passed else None
            return passed, extracted

        # regex
        match = self.pattern.search(text) if self.pattern else None
        passed = match is not None
        if self.extract:
            extracted = extract_value(text, self.extract)
        elif match is None:
            extracted = None
        elif match.groups():
            extracted = match.group(1)
        else:
            extracted = match.group(0)
        return passed, extracted


class ICLExample:
    """One in-context example: a row-shaped input and a verbatim reply."""

    def __init__(self, inputs: Dict[str, Any], output: str) -> None:
        self.inputs = inputs
        self.output = output


class ICLSetup:
    """A named collection of in-context examples."""

    def __init__(self, name: str, examples: List[ICLExample]) -> None:
        self.name = name
        self.examples = examples

    def selected(self, k: Optional[int]) -> List[ICLExample]:
        """The examples actually used: all of them, or the first ``k``."""
        if k is None or k >= len(self.examples):
            return self.examples
        return self.examples[:k]


def _parse_icl_example(raw: Any, label: str, strict: bool) -> ICLExample:
    """Validate one ``{"input": {...}, "output": "..."}`` record."""
    if not isinstance(raw, dict):
        raise ConfigError("%s must be an object with 'input' and 'output'" % label)
    if "input" not in raw:
        raise ConfigError("%s is missing required key 'input'" % label)
    if "output" not in raw:
        raise ConfigError("%s is missing required key 'output'" % label)
    inputs = raw["input"]
    if not isinstance(inputs, dict):
        raise ConfigError("%s: 'input' must be an object" % label)
    output = raw["output"]
    if isinstance(output, str):
        text = output
    elif strict or isinstance(output, (list, dict)) or output is None:
        raise ConfigError("%s: 'output' must be a string" % label)
    else:
        text = to_text(output)
    return ICLExample(dict(inputs), text)


def load_icl_file(path: str, label: str) -> List[ICLExample]:
    """Read a JSONL file of in-context examples (strict; errors exit 1)."""
    if not os.path.exists(path):
        raise ConfigError("%s: ICL example file not found: %s" % (label, path))
    examples: List[ICLExample] = []
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError as exc:
        raise ConfigError("%s: could not read ICL file %s: %s" % (label, path, exc))
    try:
        for lineno, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ConfigError(
                    "%s: %s line %d is not valid JSON: %s"
                    % (label, path, lineno, exc)
                )
            examples.append(
                _parse_icl_example(raw, "%s: %s line %d" % (label, path, lineno), True)
            )
    except OSError as exc:
        raise ConfigError("%s: could not read ICL file %s: %s" % (label, path, exc))
    finally:
        handle.close()
    return examples


class ICLConfig:
    def __init__(
        self, setups: List[ICLSetup], k: Optional[int], strategy: str
    ) -> None:
        self.setups = setups
        self.k = k
        self.strategy = strategy


def build_icl_config(raw: Any, args: Any, label: str, config_dir: str) -> ICLConfig:
    icl = _require_mapping(raw, label)

    setups_raw = icl.get("setups")
    if setups_raw is None:
        raise ConfigError("%s.setups is required" % label)
    if not isinstance(setups_raw, list) or not setups_raw:
        raise ConfigError("%s.setups must be a non-empty list" % label)

    setups: List[ICLSetup] = []
    for position, item in enumerate(setups_raw):
        slabel = "%s.setups[%d]" % (label, position)
        setup_raw = _require_mapping(item, slabel)
        name = setup_raw.get("name")
        if name is None or not str(name).strip():
            raise ConfigError("%s.name is required" % slabel)
        name = str(name)

        has_examples = setup_raw.get("examples") is not None
        has_file = setup_raw.get("file") is not None
        if has_examples == has_file:
            raise ConfigError(
                "%s must define exactly one of 'examples' or 'file'" % slabel
            )

        if has_file:
            file_path = to_text(setup_raw["file"])
            if not os.path.isabs(file_path):
                file_path = os.path.join(config_dir, file_path)
            examples = load_icl_file(file_path, slabel)
        else:
            raw_examples = setup_raw["examples"]
            if not isinstance(raw_examples, list):
                raise ConfigError("%s.examples must be a list" % slabel)
            examples = [
                _parse_icl_example(entry, "%s.examples[%d]" % (slabel, index), False)
                for index, entry in enumerate(raw_examples)
            ]
        setups.append(ICLSetup(name, examples))

    k_raw = _arg(args, "icl_k") if _arg(args, "icl_k") is not None else icl.get("k")
    k = None if k_raw is None else _as_nonnegative_int(k_raw, "%s.k" % label)

    strategy_raw = (
        _arg(args, "icl_strategy")
        if _arg(args, "icl_strategy") is not None
        else icl.get("strategy", "fixed")
    )
    strategy = str(strategy_raw).strip().lower()
    if strategy not in ICL_STRATEGIES:
        raise ConfigError(
            "%s.strategy must be one of %s, got %r"
            % (label, ", ".join(ICL_STRATEGIES), strategy)
        )

    return ICLConfig(setups, k, strategy)


class TaskConfig:
    def __init__(self) -> None:
        self.name: str = "task"
        self.api_url: str = ""
        self.model: str = ""
        self.rpm: Optional[int] = None
        self.tpm: Optional[int] = None
        self.max_concurrent: Optional[int] = None
        self.prompt_cost_per_1k: Optional[float] = None
        self.completion_cost_per_1k: Optional[float] = None
        self.budget: Optional[float] = None
        self.output_schema: Optional[Dict[str, Any]] = None
        self.limiter: RateLimiter = RateLimiter()
        self.cost_tracker: CostTracker = CostTracker()
        self.progress: Optional[ProgressReporter] = None
        self.resumed_from: int = 0
        self.system_template: Optional[str] = None
        self.user_template: Optional[str] = None
        self.scheme: str = "greedy"
        self.temperature: float = 0.0
        self.max_tokens: int = 512
        self.n: int = 1
        self.evaluation: Optional[Evaluation] = None
        self.output_field: str = "output"
        self.concurrency: int = 0
        self.timeout: float = 600.0
        self.input_path: Optional[str] = None
        self.output_path: Optional[str] = None
        self.icl: Optional[ICLConfig] = None
        self.num_solutions: int = 1
        self.max_attempts_setting: Optional[int] = None
        self.api_type: str = "chat"
        self.chat_template: str = "chatml"
        self.tools: List[ToolDef] = []
        self.max_iterations: int = DEFAULT_MAX_ITERATIONS

    @property
    def endpoint(self) -> str:
        if self.api_type == "completions":
            return self.api_url.rstrip("/") + "/v1/completions"
        return self.api_url.rstrip("/") + "/v1/chat/completions"

    @property
    def agentic(self) -> bool:
        return self.scheme == "agentic"

    @property
    def cost_configured(self) -> bool:
        return (
            self.prompt_cost_per_1k is not None
            or self.completion_cost_per_1k is not None
            or self.budget is not None
        )

    @property
    def prompt_rate(self) -> float:
        return self.prompt_cost_per_1k or 0.0

    @property
    def completion_rate(self) -> float:
        return self.completion_cost_per_1k or 0.0

    def call_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens / 1000.0) * self.prompt_rate + (
            completion_tokens / 1000.0
        ) * self.completion_rate

    def avg_attempts(self) -> float:
        """Worst-case attempts per input, used by --dry-run planning."""
        if self.scheme == "rejection":
            if self.multi_output:
                return float(self.resolved_max_attempts())
            return float(self.n)
        return 1.0

    @property
    def tools_by_name(self) -> Dict[str, ToolDef]:
        return {tool.name: tool for tool in self.tools}

    @property
    def max_attempts(self) -> int:
        return self.n if self.scheme == "rejection" else 1

    @property
    def icl_setups(self) -> List[ICLSetup]:
        return self.icl.setups if self.icl is not None else []

    @property
    def icl_k(self) -> Optional[int]:
        return self.icl.k if self.icl is not None else None

    @property
    def icl_strategy(self) -> str:
        return self.icl.strategy if self.icl is not None else "fixed"

    @property
    def multi_output(self) -> bool:
        """True when this task uses the Part 3 list output format."""
        return self.icl is not None or self.num_solutions > 1

    def resolved_max_attempts(self) -> int:
        """Attempt budget for rejection sampling in the Part 3 format."""
        if self.max_attempts_setting is not None:
            return self.max_attempts_setting
        return 3 * self.num_solutions

    @property
    def judge_model(self) -> str:
        if self.evaluation is not None and self.evaluation.model:
            return self.evaluation.model
        return self.model

    def prompt_fields(self) -> List[str]:
        fields = template_fields(self.system_template or "")
        for field in template_fields(self.user_template or ""):
            if field not in fields:
                fields.append(field)
        return fields


def _require_mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError("%s must be a mapping" % label)
    return value


def _as_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("%s must be a positive integer" % label)
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("%s must be a positive integer, got %r" % (label, value))
    if number < 1:
        raise ConfigError("%s must be a positive integer, got %r" % (label, value))
    return number


def _as_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("%s must be a non-negative integer" % label)
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("%s must be a non-negative integer, got %r" % (label, value))
    if number < 0:
        raise ConfigError("%s must be a non-negative integer, got %r" % (label, value))
    return number


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("%s must be an integer" % label)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("%s must be an integer, got %r" % (label, value))


def _as_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("%s must be a number" % label)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("%s must be a number, got %r" % (label, value))


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``override`` onto ``base``; nested mappings merge key by key."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _arg(args: Any, name: str) -> Any:
    return getattr(args, name, None)


def build_task_config(
    name: str, task: Dict[str, Any], args: Any, label: str, config_dir: str = "."
) -> TaskConfig:
    """Turn one (already merged) task mapping into a TaskConfig."""
    cfg = TaskConfig()
    cfg.name = name

    api_url = _arg(args, "api_url") if _arg(args, "api_url") is not None else task.get("api_url")
    if not api_url or not str(api_url).strip():
        raise ConfigError("%s.api_url is required" % label)
    cfg.api_url = str(api_url).strip()

    model = _arg(args, "model") if _arg(args, "model") is not None else task.get("model")
    if not model or not str(model).strip():
        raise ConfigError("%s.model is required" % label)
    cfg.model = str(model).strip()

    rate_limits = _require_mapping(
        task.get("rate_limits") or {}, "%s.rate_limits" % label
    )

    rpm_raw = _arg(args, "rpm")
    rpm_label = "--rpm"
    if rpm_raw is None:
        if rate_limits.get("rpm") is not None:
            rpm_raw = rate_limits.get("rpm")
            rpm_label = "%s.rate_limits.rpm" % label
        elif task.get("rpm") is not None:
            rpm_raw = task.get("rpm")
            rpm_label = "%s.rpm" % label
    # An omitted rpm disables request-rate limiting for this task.
    cfg.rpm = None if rpm_raw is None else _as_positive_int(rpm_raw, rpm_label)

    tpm_raw = _arg(args, "tpm")
    tpm_label = "--tpm"
    if tpm_raw is None:
        if rate_limits.get("tpm") is not None:
            tpm_raw = rate_limits.get("tpm")
            tpm_label = "%s.rate_limits.tpm" % label
        elif task.get("tpm") is not None:
            tpm_raw = task.get("tpm")
            tpm_label = "%s.tpm" % label
    cfg.tpm = None if tpm_raw is None else _as_positive_int(tpm_raw, tpm_label)

    mc_raw = _arg(args, "max_concurrent")
    mc_label = "--max-concurrent"
    if mc_raw is None:
        if rate_limits.get("max_concurrent") is not None:
            mc_raw = rate_limits.get("max_concurrent")
            mc_label = "%s.rate_limits.max_concurrent" % label
        elif task.get("max_concurrent") is not None:
            mc_raw = task.get("max_concurrent")
            mc_label = "%s.max_concurrent" % label
    cfg.max_concurrent = (
        None if mc_raw is None else _as_positive_int(mc_raw, mc_label)
    )

    cost_raw = _require_mapping(task.get("cost") or {}, "%s.cost" % label)
    if cost_raw.get("prompt_cost_per_1k") is not None:
        cfg.prompt_cost_per_1k = _as_number(
            cost_raw["prompt_cost_per_1k"], "%s.cost.prompt_cost_per_1k" % label
        )
    if cost_raw.get("completion_cost_per_1k") is not None:
        cfg.completion_cost_per_1k = _as_number(
            cost_raw["completion_cost_per_1k"],
            "%s.cost.completion_cost_per_1k" % label,
        )
    if cost_raw.get("budget") is not None:
        cfg.budget = _as_number(cost_raw["budget"], "%s.cost.budget" % label)
    if _arg(args, "budget") is not None:
        cfg.budget = _as_number(_arg(args, "budget"), "--budget")

    api_type = (
        _arg(args, "api_type")
        if _arg(args, "api_type") is not None
        else task.get("api_type", "chat")
    )
    api_type = str(api_type).strip().lower()
    if api_type not in API_TYPES:
        raise ConfigError(
            "%s.api_type must be one of %s, got %r"
            % (label, ", ".join(API_TYPES), api_type)
        )
    cfg.api_type = api_type

    chat_template = (
        _arg(args, "chat_template")
        if _arg(args, "chat_template") is not None
        else task.get("chat_template", "chatml")
    )
    chat_template = str(chat_template).strip().lower()
    if chat_template not in CHAT_TEMPLATES:
        raise ConfigError(
            "%s.chat_template must be one of %s, got %r"
            % (label, ", ".join(CHAT_TEMPLATES), chat_template)
        )
    cfg.chat_template = chat_template

    if task.get("tools") is not None:
        cfg.tools = build_tools(task["tools"], "%s.tools" % label)

    if "prompt" not in task or task.get("prompt") is None:
        raise ConfigError("%s.prompt is required" % label)
    prompt = _require_mapping(task["prompt"], "%s.prompt" % label)
    system = prompt.get("system")
    user = prompt.get("user")
    if system is None and user is None:
        raise ConfigError("%s.prompt must define 'system' and/or 'user'" % label)
    cfg.system_template = None if system is None else to_text(system)
    cfg.user_template = None if user is None else to_text(user)

    generation = _require_mapping(task.get("generation") or {}, "%s.generation" % label)

    scheme = (
        _arg(args, "scheme")
        if _arg(args, "scheme") is not None
        else generation.get("scheme", "greedy")
    )
    scheme = str(scheme).strip().lower()
    if scheme not in SCHEMES:
        raise ConfigError(
            "%s.generation.scheme must be one of %s, got %r"
            % (label, ", ".join(SCHEMES), scheme)
        )
    cfg.scheme = scheme

    max_tokens = (
        _arg(args, "max_tokens")
        if _arg(args, "max_tokens") is not None
        else generation.get("max_tokens", 512)
    )
    cfg.max_tokens = _as_positive_int(max_tokens, "%s.generation.max_tokens" % label)

    temp_raw = (
        _arg(args, "temperature")
        if _arg(args, "temperature") is not None
        else generation.get("temperature")
    )
    if scheme == "greedy":
        cfg.temperature = 0.0  # greedy always forces temperature 0.0
    elif scheme == "agentic":
        # Agentic runs are usually deterministic; any temperature >= 0 is fine.
        if temp_raw is None:
            cfg.temperature = 0.0
        else:
            cfg.temperature = _as_number(temp_raw, "%s.generation.temperature" % label)
        if cfg.temperature < 0:
            raise ConfigError(
                "%s.generation.temperature must be >= 0 for scheme 'agentic', got %s"
                % (label, cfg.temperature)
            )
    else:
        if temp_raw is None:
            cfg.temperature = 1.0
        else:
            cfg.temperature = _as_number(temp_raw, "%s.generation.temperature" % label)
        if cfg.temperature <= 0:
            raise ConfigError(
                "%s.generation.temperature must be > 0 for scheme %r, got %s"
                % (label, scheme, cfg.temperature)
            )

    n_raw = _arg(args, "n") if _arg(args, "n") is not None else generation.get("n", 1)
    cfg.n = _as_positive_int(n_raw, "%s.generation.n" % label)

    # max_iterations belongs under `generation`, but a task-level key is
    # accepted too so it can sit beside num_solutions in `defaults`.
    if task.get("max_iterations") is not None:
        cfg.max_iterations = _as_positive_int(
            task.get("max_iterations"), "%s.max_iterations" % label
        )
    if generation.get("max_iterations") is not None:
        cfg.max_iterations = _as_positive_int(
            generation.get("max_iterations"), "%s.generation.max_iterations" % label
        )
    if _arg(args, "max_iterations") is not None:
        cfg.max_iterations = _as_positive_int(
            _arg(args, "max_iterations"), "--max-iterations"
        )

    if generation.get("max_attempts") is not None:
        cfg.max_attempts_setting = _as_positive_int(
            generation.get("max_attempts"), "%s.generation.max_attempts" % label
        )

    num_solutions = (
        _arg(args, "num_solutions")
        if _arg(args, "num_solutions") is not None
        else task.get("num_solutions", 1)
    )
    cfg.num_solutions = _as_positive_int(num_solutions, "%s.num_solutions" % label)

    if task.get("icl") is not None:
        cfg.icl = build_icl_config(task["icl"], args, "%s.icl" % label, config_dir)
        validate_icl_examples(cfg, "%s.icl" % label)

    evaluation_raw = task.get("evaluation")
    if evaluation_raw is not None:
        cfg.evaluation = build_evaluation(evaluation_raw, args, "%s.evaluation" % label)

    if task.get("output_schema") is not None:
        cfg.output_schema = validate_schema_config(
            task["output_schema"], "%s.output_schema" % label
        )

    if (
        cfg.scheme == "rejection"
        and cfg.evaluation is None
        and cfg.output_schema is None
    ):
        # Rejection sampling needs something to reject on; a schema will do.
        raise ConfigError("%s.evaluation is required for scheme 'rejection'" % label)

    output_field = task.get("output_field")
    if output_field is None or not str(output_field).strip():
        raise ConfigError("%s.output_field is required" % label)
    cfg.output_field = str(output_field)

    if _arg(args, "concurrency") is not None:
        cfg.concurrency = _as_positive_int(_arg(args, "concurrency"), "--concurrency")
    else:
        # Enough in-flight requests to keep a server with `rpm` capacity busy
        # even when individual requests sit in its queue for a while.
        base = DEFAULT_CONCURRENCY if cfg.rpm is None else min(max(cfg.rpm, 8), 512)
        cfg.concurrency = max(base, cfg.max_concurrent or 0)

    cfg.limiter = RateLimiter(cfg.rpm, cfg.tpm, cfg.max_concurrent)

    return cfg


def render_icl_input(cfg: TaskConfig, example: "ICLExample") -> str:
    """The user turn for one in-context example."""
    if cfg.user_template is None:
        return json.dumps(example.inputs, ensure_ascii=False, sort_keys=True)
    return render_template(cfg.user_template, example.inputs, 0)


def validate_icl_examples(cfg: TaskConfig, label: str) -> None:
    """Fail fast if an example cannot be rendered with prompt.user."""
    if cfg.icl is None:
        return
    for setup in cfg.icl.setups:
        for index, example in enumerate(setup.selected(cfg.icl.k)):
            try:
                render_icl_input(cfg, example)
            except ConfigError as exc:
                raise ConfigError(
                    "%s: setup %r example %d cannot be rendered with prompt.user: %s"
                    % (label, setup.name, index, exc)
                )


def build_evaluation(raw: Any, args: Any, label: str) -> Evaluation:
    evaluation = _require_mapping(raw, label)
    eval_type = evaluation.get("type")
    if eval_type is None:
        raise ConfigError("%s.type is required" % label)
    eval_type = str(eval_type).strip()
    if eval_type not in EVAL_TYPES:
        raise ConfigError(
            "%s.type must be one of %s, got %r" % (label, ", ".join(EVAL_TYPES), eval_type)
        )

    answer_field = evaluation.get("answer_field")
    pattern = evaluation.get("pattern")
    extract = evaluation.get("extract")

    if eval_type in ("exact_match", "contains"):
        if answer_field is None or not str(answer_field).strip():
            raise ConfigError("%s.answer_field is required for type %r" % (label, eval_type))
        answer_field = str(answer_field)
    elif eval_type == "regex":
        if pattern is None or not str(pattern):
            raise ConfigError("%s.pattern is required for type 'regex'" % label)
        answer_field = str(answer_field) if answer_field is not None else None
    else:
        answer_field = str(answer_field) if answer_field is not None else None

    if pattern is not None:
        pattern = to_text(pattern)
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError("%s.pattern is not a valid regex: %s" % (label, exc))

    if extract is not None:
        extract = str(extract).strip()
        if extract not in EXTRACT_METHODS:
            raise ConfigError(
                "%s.extract must be one of %s, got %r"
                % (label, ", ".join(EXTRACT_METHODS), extract)
            )

    judge_system: Optional[str] = None
    judge_user: Optional[str] = None
    threshold: Optional[float] = None
    model: Optional[str] = None
    command_template: Optional[str] = None
    success_exit_code = 0

    if eval_type == "llm_judge":
        judge_raw = evaluation.get("judge_prompt")
        if judge_raw is None:
            raise ConfigError("%s.judge_prompt is required for type 'llm_judge'" % label)
        judge_prompt = _require_mapping(judge_raw, "%s.judge_prompt" % label)
        system = judge_prompt.get("system")
        user = judge_prompt.get("user")
        if system is None and user is None:
            raise ConfigError(
                "%s.judge_prompt must define 'system' and/or 'user'" % label
            )
        judge_system = None if system is None else to_text(system)
        judge_user = None if user is None else to_text(user)

        if evaluation.get("threshold") is None:
            raise ConfigError("%s.threshold is required for type 'llm_judge'" % label)
        threshold = _as_number(evaluation.get("threshold"), "%s.threshold" % label)

        if extract is None:
            extract = "first_number"

        eval_model = _arg(args, "eval_model")
        if eval_model is not None and str(eval_model).strip():
            model = str(eval_model).strip()
        elif evaluation.get("model") is not None and str(evaluation["model"]).strip():
            model = str(evaluation["model"]).strip()

    if eval_type == "script":
        command_template = evaluation.get("command_template")
        if command_template is None or not str(command_template).strip():
            raise ConfigError(
                "%s.command_template is required for type 'script'" % label
            )
        command_template = to_text(command_template)
        if evaluation.get("success_exit_code") is not None:
            success_exit_code = _as_int(
                evaluation.get("success_exit_code"), "%s.success_exit_code" % label
            )

    return Evaluation(
        eval_type,
        answer_field,
        extract,
        pattern,
        judge_system=judge_system,
        judge_user=judge_user,
        threshold=threshold,
        model=model,
        command_template=command_template,
        success_exit_code=success_exit_code,
    )


def read_config_file(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise ConfigError("config file not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError("could not parse YAML config %s: %s" % (path, exc))
    except OSError as exc:
        raise ConfigError("could not read config %s: %s" % (path, exc))

    if raw is None:
        raise ConfigError("config file is empty: %s" % path)
    return _require_mapping(raw, "config")


def is_multi_task(raw: Dict[str, Any]) -> bool:
    """A top-level 'task' key always means the Part 1 single-task format."""
    if "task" in raw:
        return False
    return "tasks" in raw


def load_config(path: str, args: Any) -> TaskConfig:
    """Load a single-task (Part 1) config."""
    raw = read_config_file(path)
    if is_multi_task(raw):
        raise ConfigError("config %s defines multiple tasks" % path)

    if "task" in raw:
        task = _require_mapping(raw["task"], "'task'")
    elif "prompt" in raw:
        task = raw  # tolerate a config written without the 'task' wrapper
    else:
        raise ConfigError("config must contain a 'task' section")

    name = str(task.get("name") or "task")
    config_dir = os.path.dirname(os.path.abspath(path))
    return build_task_config(name, task, args, "task", config_dir)


def load_multi_config(
    path: str, args: Any, selected: Optional[Sequence[str]] = None
) -> List[TaskConfig]:
    """Load a `defaults` + `tasks` config, building only the selected tasks."""
    raw = read_config_file(path)
    defaults = _require_mapping(raw.get("defaults") or {}, "defaults")
    tasks_raw = raw.get("tasks")
    if tasks_raw is None:
        raise ConfigError("config must contain a 'tasks' section")
    tasks = _require_mapping(tasks_raw, "tasks")
    if not tasks:
        raise ConfigError("config 'tasks' section is empty")

    names = list(tasks.keys())
    if selected:
        unknown = [name for name in selected if name not in tasks]
        if unknown:
            raise ConfigError(
                "unknown task %r; config defines: %s"
                % (unknown[0], ", ".join(str(n) for n in names))
            )
        names = [name for name in names if name in set(selected)]

    config_dir = os.path.dirname(os.path.abspath(path))
    configs: List[TaskConfig] = []
    for name in names:
        merged = deep_merge(defaults, _require_mapping(tasks[name], "tasks.%s" % name))
        merged.pop("name", None)
        configs.append(
            build_task_config(str(name), merged, args, "tasks.%s" % name, config_dir)
        )
    return configs


def load_rows(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        raise ConfigError("input file not found: %s" % path)
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ConfigError(
                        "input line %d is not valid JSON: %s" % (lineno + 1, exc)
                    )
                if not isinstance(obj, dict):
                    raise ConfigError(
                        "input line %d must be a JSON object" % (lineno + 1)
                    )
                rows.append(obj)
    except OSError as exc:
        raise ConfigError("could not read input %s: %s" % (path, exc))
    return rows


def validate_rows(cfg: TaskConfig, rows: List[Dict[str, Any]]) -> None:
    """Fail fast (exit 1) before any API call if a row cannot be used."""
    fields = cfg.prompt_fields()
    extra_fields: List[str] = []
    answer_field = None
    if cfg.evaluation is not None:
        extra_fields = cfg.evaluation.row_fields()
        if cfg.evaluation.answer_field:
            answer_field = cfg.evaluation.answer_field

    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise ConfigError(
                    "row %d: missing field %r referenced by prompt template"
                    % (index, field)
                )
        if answer_field is not None and answer_field not in row:
            raise ConfigError(
                "row %d: missing field %r required by task.evaluation.answer_field"
                % (index, answer_field)
            )
        for field in extra_fields:
            if field not in row:
                raise ConfigError(
                    "row %d: missing field %r referenced by task.evaluation"
                    % (index, field)
                )


# --------------------------------------------------------------------------- #
# Structured output validation (a JSON Schema draft 7 subset)
# --------------------------------------------------------------------------- #


def _json_type_name(value: Any) -> str:
    """Draft-7 type name for a decoded JSON value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "integer":
        # Draft 7: 1.0 is a valid integer, true is not.
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and float(value).is_integer()
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True  # an unknown type keyword constrains nothing


def _json_equal(left: Any, right: Any) -> bool:
    """Equality that keeps booleans distinct from 0/1."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            _json_equal(left[key], right[key]) for key in left
        )
    return left == right


def _schema_prefix(path: str) -> str:
    return "" if not path else "%s: " % path


def _child_path(path: str, name: Any) -> str:
    return "%s.%s" % (path, name) if path else str(name)


def _item_path(path: str, index: int) -> str:
    return "%s[%d]" % (path, index)


def _describe(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


def _as_schema_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def validate_json_schema(value: Any, schema: Any, path: str = "") -> Optional[str]:
    """Validate ``value``; return None when valid or a human-readable message."""
    if not isinstance(schema, dict):
        return None
    prefix = _schema_prefix(path)

    expected = schema.get("type")
    if expected is not None:
        options = expected if isinstance(expected, list) else [expected]
        names = [str(option) for option in options]
        if not any(_type_matches(value, name) for name in names):
            return "%sExpected type %s, got %s" % (
                prefix,
                " or ".join(names),
                _json_type_name(value),
            )

    enum = schema.get("enum")
    if isinstance(enum, list):
        if not any(_json_equal(value, option) for option in enum):
            return "%sValue %s is not one of the allowed values: %s" % (
                prefix,
                _describe(value),
                ", ".join(_describe(option) for option in enum),
            )

    number = _as_schema_number(value)
    if number is not None:
        minimum = _as_schema_number(schema.get("minimum"))
        if minimum is not None and number < minimum:
            return "%sValue %s is less than minimum %s" % (
                prefix, _describe(value), _describe(schema.get("minimum"))
            )
        maximum = _as_schema_number(schema.get("maximum"))
        if maximum is not None and number > maximum:
            return "%sValue %s is greater than maximum %s" % (
                prefix, _describe(value), _describe(schema.get("maximum"))
            )

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and not isinstance(min_length, bool):
            if len(value) < min_length:
                return "%sString is shorter than minLength %d (length %d)" % (
                    prefix, min_length, len(value)
                )
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and not isinstance(max_length, bool):
            if len(value) > max_length:
                return "%sString is longer than maxLength %d (length %d)" % (
                    prefix, max_length, len(value)
                )
        pattern = schema.get("pattern")
        if pattern is not None:
            try:
                compiled = re.compile(to_text(pattern))
            except re.error:
                compiled = None
            if compiled is not None and compiled.search(value) is None:
                return "%sString does not match pattern %s" % (
                    prefix, _describe(to_text(pattern))
                )

    if isinstance(value, dict):
        required = schema.get("required")
        if isinstance(required, list):
            for name in required:
                if name not in value:
                    return "%sMissing required field: %s" % (prefix, name)
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, subschema in properties.items():
                if name in value:
                    error = validate_json_schema(
                        value[name], subschema, _child_path(path, name)
                    )
                    if error is not None:
                        return error

    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                error = validate_json_schema(item, items, _item_path(path, index))
                if error is not None:
                    return error
        elif isinstance(items, list):
            # Tuple validation: schema i applies to element i.
            for index, subschema in enumerate(items):
                if index >= len(value):
                    break
                error = validate_json_schema(
                    value[index], subschema, _item_path(path, index)
                )
                if error is not None:
                    return error

    return None


def parse_structured_output(
    text: str, schema: Any
) -> Tuple[bool, Any, Optional[str]]:
    """Parse ``text`` as JSON and validate it: (ok, value, error_message)."""
    stripped = (text or "").strip()
    if not stripped:
        return False, None, "Invalid JSON: response is empty"
    try:
        value = json.loads(stripped)
    except ValueError as exc:
        return False, None, "Invalid JSON: %s" % exc
    error = validate_json_schema(value, schema)
    if error is not None:
        return False, None, error
    return True, value, None


def validate_schema_config(raw: Any, label: str) -> Dict[str, Any]:
    """Shallow sanity-check of a declared output_schema."""
    schema = _require_mapping(raw, label)
    pattern = schema.get("pattern")
    if pattern is not None:
        try:
            re.compile(to_text(pattern))
        except re.error as exc:
            raise ConfigError("%s.pattern is not a valid regex: %s" % (label, exc))
    properties = schema.get("properties")
    if properties is not None:
        properties = _require_mapping(properties, "%s.properties" % label)
        for name, sub in properties.items():
            if sub is not None:
                validate_schema_config(sub, "%s.properties.%s" % (label, name))
    items = schema.get("items")
    if isinstance(items, list):
        for index, sub in enumerate(items):
            validate_schema_config(sub, "%s.items[%d]" % (label, index))
    elif items is not None:
        validate_schema_config(items, "%s.items" % label)
    required = schema.get("required")
    if required is not None and not isinstance(required, list):
        raise ConfigError("%s.required must be a list" % label)
    enum = schema.get("enum")
    if enum is not None and not isinstance(enum, list):
        raise ConfigError("%s.enum must be a list" % label)
    return schema


# --------------------------------------------------------------------------- #
# Token estimation, rate limiting, cost accounting and progress
# --------------------------------------------------------------------------- #


def count_words(text: str) -> int:
    return len(text.split())


def estimate_tokens(words: int) -> int:
    """`1 token ~= 0.75 words`, rounded up."""
    return int(math.ceil(words / WORDS_PER_TOKEN))


def messages_word_count(messages: Sequence[Dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += count_words(content)
        elif content is not None:
            total += count_words(to_text(content))
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict):
                total += count_words(to_text(call))
    return total


class _TokenEntry:
    """One reservation inside the sliding TPM window."""

    __slots__ = ("time", "tokens")

    def __init__(self, when: float, tokens: int) -> None:
        self.time = when
        self.tokens = tokens


class RateLimiter:
    """Sliding 60 second RPM and TPM windows plus a hard concurrency cap."""

    def __init__(
        self,
        rpm: Optional[int] = None,
        tpm: Optional[int] = None,
        max_concurrent: Optional[int] = None,
    ) -> None:
        self.rpm = rpm
        self.tpm = tpm
        self.max_concurrent = max_concurrent
        self._requests: "deque[float]" = deque()
        self._tokens: List[_TokenEntry] = []
        self._lock: Optional[asyncio.Lock] = None
        self._slots: Optional[asyncio.Semaphore] = None

    def _ensure(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        if self._slots is None and self.max_concurrent:
            self._slots = asyncio.Semaphore(self.max_concurrent)

    def _prune(self, now: float) -> None:
        cutoff = now - RATE_WINDOW
        while self._requests and self._requests[0] <= cutoff:
            self._requests.popleft()
        if self._tokens:
            self._tokens = [e for e in self._tokens if e.time > cutoff]

    async def acquire(self, reserve_tokens: int) -> Optional[_TokenEntry]:
        """Wait until both budgets have room, then book this request."""
        if self.rpm is None and self.tpm is None:
            return None
        self._ensure()
        assert self._lock is not None
        while True:
            async with self._lock:
                now = time.monotonic()
                self._prune(now)
                wait = 0.0
                if self.rpm is not None and len(self._requests) >= self.rpm:
                    wait = max(wait, self._requests[0] + RATE_WINDOW - now)
                if self.tpm is not None and self._tokens:
                    used = sum(entry.tokens for entry in self._tokens)
                    if used + reserve_tokens > self.tpm:
                        oldest = min(entry.time for entry in self._tokens)
                        wait = max(wait, oldest + RATE_WINDOW - now)
                if wait <= 0.0:
                    if self.rpm is not None:
                        self._requests.append(now)
                    if self.tpm is None:
                        return None
                    entry = _TokenEntry(now, max(0, reserve_tokens))
                    self._tokens.append(entry)
                    return entry
            await asyncio.sleep(min(max(wait, 0.005), RATE_WINDOW))

    def settle(self, entry: Optional[_TokenEntry], actual_tokens: int) -> None:
        """Replace a reservation with the tokens the API actually reported."""
        if entry is not None:
            entry.tokens = max(0, int(actual_tokens))

    def slot(self) -> Any:
        self._ensure()
        return _ConcurrencySlot(self._slots)


class _ConcurrencySlot:
    """Async context manager for one in-flight slot (a no-op when uncapped)."""

    def __init__(self, semaphore: Optional[asyncio.Semaphore]) -> None:
        self._semaphore = semaphore

    async def __aenter__(self) -> "_ConcurrencySlot":
        if self._semaphore is not None:
            await self._semaphore.acquire()
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        if self._semaphore is not None:
            self._semaphore.release()
        return False


class CostTracker:
    """Running prompt/completion cost across every task, plus the budget."""

    def __init__(self, enabled: bool = False, budget: Optional[float] = None) -> None:
        self.enabled = enabled
        self.budget = budget
        self.prompt_cost = 0.0
        self.completion_cost = 0.0
        self.budget_exceeded = False

    @property
    def total(self) -> float:
        return self.prompt_cost + self.completion_cost

    def record(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        prompt_rate: float,
        completion_rate: float,
    ) -> None:
        self.prompt_cost += (prompt_tokens / 1000.0) * prompt_rate
        self.completion_cost += (completion_tokens / 1000.0) * completion_rate
        if self.budget is not None and self.total >= self.budget:
            self.budget_exceeded = True

    def exhausted(self) -> bool:
        if self.budget is None:
            return False
        if self.total >= self.budget:
            self.budget_exceeded = True
            return True
        return False

    def summary(self) -> Dict[str, Any]:
        total = _round_cost(self.total)
        budget = None if self.budget is None else float(self.budget)
        remaining = None if budget is None else _round_cost(budget - self.total)
        return {
            "total": total,
            "prompt": _round_cost(self.prompt_cost),
            "completion": _round_cost(self.completion_cost),
            "budget": budget,
            "budget_remaining": remaining,
            "budget_exceeded": bool(self.budget_exceeded),
        }


def _round_cost(value: float) -> float:
    """Keep well beyond four decimal places while dropping float noise."""
    return round(float(value) + 0.0, 10)


class ProgressReporter:
    """`--progress` lines on stderr, at most one every 5s or 10% of inputs."""

    def __init__(
        self,
        total: int,
        has_evaluation: bool,
        cost: Optional[CostTracker] = None,
        stream: Any = None,
    ) -> None:
        self.total = total
        self.has_evaluation = has_evaluation
        self.cost = cost
        self.stream = stream if stream is not None else sys.stderr
        self.completed = 0
        self.passed = 0
        self.failed = 0
        self.api_calls = 0
        self.started = time.monotonic()
        self._last_time = self.started
        self._last_completed = 0
        self._ticker: Optional[asyncio.Task] = None
        self._stop = False
        self._emitted = False
        self._step = max(1, int(math.ceil(total * PROGRESS_FRACTION))) if total else 1

    def start(self) -> None:
        if self._ticker is None:
            self._ticker = asyncio.ensure_future(self._tick())

    async def _tick(self) -> None:
        try:
            while not self._stop:
                await asyncio.sleep(0.25)
                if self._stop:
                    return
                if time.monotonic() - self._last_time >= PROGRESS_INTERVAL:
                    self.emit()
        except asyncio.CancelledError:
            return

    async def stop(self) -> None:
        self._stop = True
        ticker, self._ticker = self._ticker, None
        if ticker is not None:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker

    def note_api_call(self) -> None:
        self.api_calls += 1

    def note_row(self, passed: Optional[bool]) -> None:
        self.completed += 1
        if passed is True:
            self.passed += 1
        elif passed is False:
            self.failed += 1
        if self.completed - self._last_completed >= self._step:
            self.emit()
        elif time.monotonic() - self._last_time >= PROGRESS_INTERVAL:
            self.emit()

    def line(self) -> str:
        total = self.total
        done = self.completed
        percent = int(done * 100 // total) if total else 100
        parts = ["[%d/%d] %d%% complete" % (done, total, percent)]
        if self.has_evaluation:
            parts.append("%d passed, %d failed" % (self.passed, self.failed))
        elapsed = max(1e-9, time.monotonic() - self.started)
        parts.append("%.1f rpm" % (self.api_calls / elapsed * 60.0))
        if self.cost is not None and self.cost.enabled:
            parts.append("$%.2f spent" % self.cost.total)
        remaining = max(0, total - done)
        eta = (remaining * elapsed / done) if done > 0 else 0.0
        parts.append("ETA: %ds" % int(round(eta)))
        return " | ".join(parts)

    def emit(self, final: bool = False) -> None:
        if final and self._emitted and self.completed == self._last_completed:
            return  # the 10% rule already printed this exact line
        self._emitted = True
        self._last_time = time.monotonic()
        self._last_completed = self.completed
        try:
            self.stream.write(self.line() + "\n")
            self.stream.flush()
        except (OSError, ValueError):
            pass


# --------------------------------------------------------------------------- #
# API client
# --------------------------------------------------------------------------- #


class Stats:
    def __init__(self) -> None:
        self.api_calls = 0
        self.first_start: Optional[float] = None
        self.last_end: Optional[float] = None

    def mark(self, start: float, end: float) -> None:
        if self.first_start is None or start < self.first_start:
            self.first_start = start
        if self.last_end is None or end > self.last_end:
            self.last_end = end

    def merge(self, other: "Stats") -> None:
        self.api_calls += other.api_calls
        if other.first_start is not None:
            if self.first_start is None or other.first_start < self.first_start:
                self.first_start = other.first_start
        if other.last_end is not None:
            if self.last_end is None or other.last_end > self.last_end:
                self.last_end = other.last_end

    @property
    def elapsed(self) -> float:
        if self.first_start is None or self.last_end is None:
            return 0.0
        return max(0.0, self.last_end - self.first_start)


class CallResult:
    def __init__(
        self,
        ok: bool,
        content: str = "",
        meta: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        message: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.ok = ok
        self.content = content
        self.meta = meta or {}
        self.error = error
        self.tool_calls = tool_calls or []
        self.message = message


async def call_api(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    messages: List[Dict[str, Any]],
    stats: Stats,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    tools: Optional[List[ToolDef]] = None,
    hold_slot: bool = True,
) -> CallResult:
    """One logical attempt: up to MAX_HTTP_TRIES requests, retrying 5xx."""
    if hold_slot:
        async with cfg.limiter.slot():
            return await _call_api(
                session, cfg, messages, stats, model, temperature, tools
            )
    return await _call_api(session, cfg, messages, stats, model, temperature, tools)


async def _call_api(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    messages: List[Dict[str, Any]],
    stats: Stats,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    tools: Optional[List[ToolDef]] = None,
) -> CallResult:
    model = cfg.model if model is None else model
    temperature = cfg.temperature if temperature is None else temperature
    if cfg.api_type == "completions":
        # Tool definitions are rendered into the prompt, not sent natively.
        rendered = render_chat_prompt(cfg.chat_template, messages, tools)
        prompt_words = count_words(rendered)
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": rendered,
            "temperature": temperature,
            "max_tokens": cfg.max_tokens,
        }
    else:
        prompt_words = messages_word_count(messages)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": cfg.max_tokens,
        }
        if tools:
            payload["tools"] = [tool.spec() for tool in tools]

    # Reserve the worst case for this request: the estimated prompt plus the
    # completion the server is allowed to produce.
    reserve = estimate_tokens(prompt_words) + cfg.max_tokens
    last_error = "request failed"
    last_latency_ms = 0

    for attempt_index in range(MAX_HTTP_TRIES):
        if cfg.cost_tracker.exhausted():
            raise BudgetExceeded()
        entry = await cfg.limiter.acquire(reserve)
        start = time.monotonic()
        stats.api_calls += 1
        if cfg.progress is not None:
            cfg.progress.note_api_call()
        retryable = False
        try:
            async with session.post(cfg.endpoint, json=payload) as response:
                body = await response.read()
                end = time.monotonic()
                stats.mark(start, end)
                last_latency_ms = int(round((end - start) * 1000))
                status = response.status
                if status >= 500:
                    cfg.limiter.settle(entry, 0)
                    last_error = "HTTP %d" % status
                    retryable = True
                elif status >= 400:
                    cfg.limiter.settle(entry, 0)
                    return CallResult(
                        False,
                        meta=_error_meta(model, last_latency_ms, "HTTP %d" % status),
                        error="HTTP %d" % status,
                    )
                else:
                    try:
                        data = json.loads(body.decode("utf-8"))
                        choice = data["choices"][0]
                        if cfg.api_type == "completions":
                            text = choice.get("text")
                            content = "" if text is None else str(text)
                            tool_calls = parse_text_tool_calls(content)
                            message: Dict[str, Any] = {
                                "role": "assistant",
                                "content": content,
                            }
                        else:
                            message = choice.get("message") or {}
                            if not isinstance(message, dict):
                                message = {"role": "assistant", "content": ""}
                            raw_content = message.get("content")
                            content = "" if raw_content is None else str(raw_content)
                            tool_calls = parse_message_tool_calls(message)
                        usage = data.get("usage") or {}
                        meta = {
                            "model": model,
                            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                            "completion_tokens": int(
                                usage.get("completion_tokens") or 0
                            ),
                            "total_tokens": int(usage.get("total_tokens") or 0),
                            "latency_ms": last_latency_ms,
                            "finish_reason": choice.get("finish_reason"),
                        }
                        # The window now holds what was actually consumed
                        # instead of the pre-dispatch reservation.
                        cfg.limiter.settle(
                            entry,
                            meta["prompt_tokens"] + meta["completion_tokens"],
                        )
                        cfg.cost_tracker.record(
                            meta["prompt_tokens"],
                            meta["completion_tokens"],
                            cfg.prompt_rate,
                            cfg.completion_rate,
                        )
                        return CallResult(
                            True,
                            content=str(content),
                            meta=meta,
                            tool_calls=tool_calls,
                            message=message,
                        )
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                        cfg.limiter.settle(entry, 0)
                        message = "malformed API response: %s" % exc
                        return CallResult(
                            False,
                            meta=_error_meta(model, last_latency_ms, message),
                            error=message,
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            end = time.monotonic()
            stats.mark(start, end)
            cfg.limiter.settle(entry, 0)
            last_latency_ms = int(round((end - start) * 1000))
            last_error = "%s: %s" % (type(exc).__name__, exc) if str(exc) else type(exc).__name__
            retryable = True

        if not retryable:
            break
        if attempt_index < MAX_HTTP_TRIES - 1:
            await asyncio.sleep(min(0.2 * (2 ** attempt_index), 2.0))

    return CallResult(
        False, meta=_error_meta(model, last_latency_ms, last_error), error=last_error
    )


def _error_meta(model: str, latency_ms: int, error: str) -> Dict[str, Any]:
    return {
        "model": model,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latency_ms": latency_ms,
        "finish_reason": None,
        "error": error,
    }


# --------------------------------------------------------------------------- #
# Evaluation backends that need to do work (API call / subprocess)
# --------------------------------------------------------------------------- #


async def run_script_evaluation(
    cfg: TaskConfig, row: Dict[str, Any], index: int, response: str
) -> bool:
    """Render and run the shell command; exit code decides pass/fail."""
    evaluation = cfg.evaluation
    assert evaluation is not None and evaluation.command_template is not None
    command = render_with_response(evaluation.command_template, row, index, response)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group, so a timeout kills the tree
        )
    except OSError:
        return False

    try:
        # stdout/stderr are captured but deliberately not surfaced in output.
        await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT)
    except asyncio.TimeoutError:
        await _terminate(proc)
        return False  # timeout is a failed evaluation

    return proc.returncode == evaluation.success_exit_code


async def _terminate(proc: "asyncio.subprocess.Process") -> None:
    """Kill a timed-out command and everything it spawned."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
    try:
        # The process group is gone; this only reaps it.
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except (asyncio.TimeoutError, ProcessLookupError, OSError):
        pass


async def run_judge_evaluation(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    response: str,
    stats: Stats,
) -> Tuple[bool, Optional[str], Optional[float], Dict[str, Any]]:
    """Ask the judge model to score a response."""
    evaluation = cfg.evaluation
    assert evaluation is not None

    messages: List[Dict[str, str]] = []
    if evaluation.judge_system is not None:
        messages.append(
            {
                "role": "system",
                "content": render_with_response(
                    evaluation.judge_system, row, index, response
                ),
            }
        )
    if evaluation.judge_user is not None:
        messages.append(
            {
                "role": "user",
                "content": render_with_response(
                    evaluation.judge_user, row, index, response
                ),
            }
        )

    call = await call_api(
        session, cfg, messages, stats, model=cfg.judge_model, temperature=0.0
    )
    if not call.ok:
        return False, None, None, call.meta

    extracted = extract_value(call.content, evaluation.extract or "first_number")
    score = _to_score(extracted)
    threshold = evaluation.threshold if evaluation.threshold is not None else 0.0
    passed = score is not None and score >= threshold
    return passed, extracted, score, call.meta


async def evaluate_response(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    response: str,
    stats: Stats,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Return (passed, extracted_answer, extra) for one generated response."""
    evaluation = cfg.evaluation
    assert evaluation is not None

    if evaluation.type == "script":
        passed = await run_script_evaluation(cfg, row, index, response)
        return passed, None, {}

    if evaluation.type == "llm_judge":
        passed, extracted, score, judge_meta = await run_judge_evaluation(
            session, cfg, row, index, response, stats
        )
        return passed, extracted, {"judge_score": score, "judge_meta": judge_meta}

    passed, extracted = evaluation.evaluate(response, row)
    return passed, extracted, {}


# --------------------------------------------------------------------------- #
# Row processing
# --------------------------------------------------------------------------- #


def check_output_schema(
    cfg: TaskConfig, text: str
) -> Tuple[bool, Any, Optional[str]]:
    """Validate one response against ``output_schema``: (ok, value, error)."""
    if cfg.output_schema is None:
        return True, text, None
    return parse_structured_output(text, cfg.output_schema)


def _apply_schema_result(
    cfg: TaskConfig,
    result: Dict[str, Any],
    schema_valid: Optional[bool],
    schema_error: Optional[str],
) -> None:
    """Attach schema_valid / schema_error to a row's result block."""
    if cfg.output_schema is None:
        return
    result["schema_valid"] = bool(schema_valid)
    if not schema_valid and schema_error is not None:
        result["schema_error"] = schema_error


def build_messages(
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    setup: Optional[ICLSetup] = None,
) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    if cfg.system_template is not None:
        messages.append(
            {"role": "system", "content": render_template(cfg.system_template, row, index)}
        )
    if setup is not None:
        # Examples sit between the system message and the final user message as
        # alternating user/assistant turns.
        for example in setup.selected(cfg.icl_k):
            messages.append({"role": "user", "content": render_icl_input(cfg, example)})
            messages.append({"role": "assistant", "content": example.output})
    if cfg.user_template is not None:
        messages.append(
            {"role": "user", "content": render_template(cfg.user_template, row, index)}
        )
    return messages


def select_setup(
    cfg: TaskConfig, attempt_index: int, rng: "random.Random"
) -> Optional[ICLSetup]:
    """Pick the ICL setup for one attempt according to icl.strategy."""
    setups = cfg.icl_setups
    if not setups:
        return None
    strategy = cfg.icl_strategy
    if strategy == "random":
        return rng.choice(setups)
    if strategy == "round_robin":
        return setups[attempt_index % len(setups)]
    return setups[0]  # fixed


def setup_name(setup: Optional[ICLSetup]) -> Optional[str]:
    return setup.name if setup is not None else None


MULTI_ATTEMPT_CAP = 10000  # guards against a pathological attempt budget


def _greedy_plan(cfg: TaskConfig, rng: "random.Random") -> List[Optional[ICLSetup]]:
    """Setups a greedy run walks through, at most once each."""
    setups = cfg.icl_setups
    if not setups:
        return [None]
    if cfg.num_solutions > 1:
        # Re-running the same setup at temperature 0 would only repeat itself,
        # so the declared setups are the whole budget.
        return list(setups)
    return [select_setup(cfg, 0, rng)]


async def process_row_multi(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    stats: Stats,
) -> Dict[str, Any]:
    """Collect up to ``num_solutions`` solutions for one row (list format)."""
    rng = random.Random()
    plan: Optional[List[Optional[ICLSetup]]] = None

    if cfg.scheme == "greedy":
        plan = _greedy_plan(cfg, rng)
        limit = len(plan)
    elif cfg.scheme == "sample":
        limit = cfg.num_solutions
    else:  # rejection
        limit = min(cfg.resolved_max_attempts(), MULTI_ATTEMPT_CAP)

    outputs: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    attempts = 0

    for attempt_index in range(limit):
        if len(outputs) >= cfg.num_solutions:
            break
        setup = plan[attempt_index] if plan is not None else select_setup(
            cfg, attempt_index, rng
        )
        name = setup_name(setup)
        messages = build_messages(cfg, row, index, setup)

        attempts += 1
        call = await call_api(session, cfg, messages, stats)
        meta = dict(call.meta)
        meta["icl_setup"] = name

        if not call.ok:
            if cfg.output_schema is not None:
                meta["schema_valid"] = False
            meta["evaluation_passed"] = None if cfg.evaluation is None else False
            metas.append(meta)
            continue

        # Schema validation runs before any other evaluation.
        ok, value, error = check_output_schema(cfg, call.content)
        if not ok:
            meta["schema_valid"] = False
            meta["schema_error"] = error
            meta["evaluation_passed"] = None if cfg.evaluation is None else False
            metas.append(meta)
            continue
        if cfg.output_schema is not None:
            meta["schema_valid"] = True

        if cfg.evaluation is None:
            meta["evaluation_passed"] = None
            metas.append(meta)
            outputs.append({cfg.output_field: value, "icl_setup": name})
            continue

        passed, _extracted, extra = await evaluate_response(
            session, cfg, row, index, call.content, stats
        )
        if "judge_meta" in extra:
            meta["judge_meta"] = extra["judge_meta"]
        meta["evaluation_passed"] = passed
        metas.append(meta)

        # Rejection sampling keeps only passing solutions; the other schemes
        # keep everything the API returned and merely record the verdict.
        if passed or cfg.scheme != "rejection":
            outputs.append({cfg.output_field: value, "icl_setup": name})

    if cfg.evaluation is None:
        passed_count = len(outputs)
    else:
        passed_count = sum(1 for meta in metas if meta.get("evaluation_passed") is True)

    return {
        "input": row,
        "output": outputs,
        "result": {
            "passed": passed_count,
            "failed": attempts - passed_count,
            "attempts": attempts,
        },
        "meta": metas,
    }


# --------------------------------------------------------------------------- #
# Agentic generation
# --------------------------------------------------------------------------- #


def _iteration_detail(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Per-iteration record kept in meta.iterations_detail."""
    detail = {
        "prompt_tokens": int(meta.get("prompt_tokens") or 0),
        "completion_tokens": int(meta.get("completion_tokens") or 0),
        "total_tokens": int(meta.get("total_tokens") or 0),
        "latency_ms": int(meta.get("latency_ms") or 0),
        "finish_reason": meta.get("finish_reason"),
    }
    if meta.get("error"):
        detail["error"] = meta["error"]
    return detail


class AgenticResult:
    """The outcome of one agentic loop (one solution)."""

    def __init__(
        self,
        content: Optional[str],
        iterations: int,
        tool_calls: List[Dict[str, Any]],
        meta: Dict[str, Any],
        finish_reason: Optional[str],
    ) -> None:
        self.content = content
        self.iterations = iterations
        self.tool_calls = tool_calls
        self.meta = meta
        self.finish_reason = finish_reason

    @property
    def hit_max_iterations(self) -> bool:
        return self.finish_reason == "max_iterations"


async def execute_tool_call(cfg: TaskConfig, call: ToolCall) -> str:
    """Run one requested tool call and return its textual result."""
    if call.error:
        return "ERROR: %s" % call.error
    tool = cfg.tools_by_name.get(call.name)
    if tool is None:
        return "ERROR: unknown tool '%s'" % call.name
    try:
        return await tool.run(call.args)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # a handler must never break the loop
        return "ERROR: %s" % exc


def build_tool_result_message(
    cfg: TaskConfig, call: ToolCall, result: str
) -> Dict[str, Any]:
    message: Dict[str, Any] = {
        "role": "tool",
        "name": call.name,
        "content": result,
    }
    if cfg.api_type != "completions":
        message["tool_call_id"] = call.id
    return message


async def run_agentic_loop(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    stats: Stats,
    setup: Optional[ICLSetup] = None,
) -> AgenticResult:
    """Call the model, run the tools it asks for, repeat until a final answer."""
    # One loop holds a single concurrency slot for its whole lifetime, while
    # each of its requests still books RPM and TPM individually.
    async with cfg.limiter.slot():
        return await _run_agentic_loop(session, cfg, row, index, stats, setup)


async def _run_agentic_loop(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    stats: Stats,
    setup: Optional[ICLSetup] = None,
) -> AgenticResult:
    messages: List[Dict[str, Any]] = list(build_messages(cfg, row, index, setup))
    details: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    iterations = 0
    content: Optional[str] = None
    finish_reason: Optional[str] = "max_iterations"
    error: Optional[str] = None
    started = time.monotonic()

    while iterations < cfg.max_iterations:
        call = await call_api(
            session, cfg, messages, stats, tools=cfg.tools or None, hold_slot=False
        )
        iterations += 1
        details.append(_iteration_detail(call.meta))

        if not call.ok:
            finish_reason = call.meta.get("finish_reason")
            error = call.error
            content = None
            break

        if call.tool_calls:
            # Record the assistant turn verbatim, then every tool result.
            messages.append(
                call.message
                if call.message is not None
                else {"role": "assistant", "content": call.content}
            )
            for tool_call in call.tool_calls:
                result = await execute_tool_call(cfg, tool_call)
                records.append(
                    {
                        "iteration": iterations,
                        "tool": tool_call.name,
                        "args": tool_call.args,
                        "result": result,
                    }
                )
                messages.append(build_tool_result_message(cfg, tool_call, result))
            continue

        content = call.content
        finish_reason = call.meta.get("finish_reason") or "stop"
        break

    latency_ms = int(round((time.monotonic() - started) * 1000))
    meta: Dict[str, Any] = {
        "total_prompt_tokens": sum(d["prompt_tokens"] for d in details),
        "total_completion_tokens": sum(d["completion_tokens"] for d in details),
        "total_tokens": sum(d["total_tokens"] for d in details),
        "latency_ms": latency_ms,
        "finish_reason": finish_reason,
        "iterations_detail": details,
    }
    if error:
        meta["error"] = error
    return AgenticResult(content, iterations, records, meta, finish_reason)


async def process_row_agentic(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    stats: Stats,
) -> Dict[str, Any]:
    """One agentic loop for a row, in the part 1 single-output format."""
    loop = await run_agentic_loop(session, cfg, row, index, stats)
    meta = dict(loop.meta)
    is_judge = cfg.evaluation is not None and cfg.evaluation.type == "llm_judge"

    extracted: Optional[str] = None
    score: Optional[float] = None
    schema_valid: Optional[bool] = None
    schema_error: Optional[str] = None
    payload: Any = None
    passed: Optional[bool] = None

    if loop.content is None:
        # No final text: a failed run, or the iteration limit.
        if cfg.output_schema is not None:
            schema_valid = False
            schema_error = "Invalid JSON: no response (%s)" % (
                loop.finish_reason or "request failed"
            )
            passed = False
        elif loop.hit_max_iterations:
            passed = False
        else:
            passed = None if cfg.evaluation is None else False
    else:
        ok, value, error = check_output_schema(cfg, loop.content)
        if not ok:
            schema_valid = False
            schema_error = error
            passed = False
        else:
            payload = value
            if cfg.output_schema is not None:
                schema_valid = True
            if cfg.evaluation is None:
                passed = True if cfg.output_schema is not None else None
            else:
                passed, extracted, extra = await evaluate_response(
                    session, cfg, row, index, loop.content, stats
                )
                if "judge_meta" in extra:
                    meta["judge_meta"] = extra["judge_meta"]
                score = extra.get("judge_score")

    output = None if payload is None else {cfg.output_field: payload}

    result: Dict[str, Any] = {
        "passed": passed,
        "extracted_answer": extracted,
        "attempts": 1,
        "iterations": loop.iterations,
        "tool_calls": loop.tool_calls,
    }
    if is_judge:
        result["judge_score"] = _json_number(score)
    _apply_schema_result(cfg, result, schema_valid, schema_error)

    return {"input": row, "output": output, "result": result, "meta": meta}


async def process_row_multi_agentic(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    stats: Stats,
) -> Dict[str, Any]:
    """``num_solutions`` independent agentic loops, in the part 3 list format."""
    rng = random.Random()
    outputs: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    attempts = 0

    for attempt_index in range(cfg.num_solutions):
        setup = select_setup(cfg, attempt_index, rng)
        name = setup_name(setup)
        attempts += 1

        loop = await run_agentic_loop(session, cfg, row, index, stats, setup)
        meta = dict(loop.meta)
        meta["icl_setup"] = name

        if loop.content is None:
            if cfg.output_schema is not None:
                meta["schema_valid"] = False
            meta["evaluation_passed"] = None if cfg.evaluation is None else False
            metas.append(meta)
            continue

        ok, value, error = check_output_schema(cfg, loop.content)
        if not ok:
            meta["schema_valid"] = False
            meta["schema_error"] = error
            meta["evaluation_passed"] = None if cfg.evaluation is None else False
            metas.append(meta)
            continue
        if cfg.output_schema is not None:
            meta["schema_valid"] = True

        if cfg.evaluation is None:
            meta["evaluation_passed"] = None
            metas.append(meta)
            outputs.append({cfg.output_field: value, "icl_setup": name})
            continue

        passed, _extracted, extra = await evaluate_response(
            session, cfg, row, index, loop.content, stats
        )
        if "judge_meta" in extra:
            meta["judge_meta"] = extra["judge_meta"]
        meta["evaluation_passed"] = passed
        metas.append(meta)
        outputs.append({cfg.output_field: value, "icl_setup": name})

    if cfg.evaluation is None:
        passed_count = len(outputs)
    else:
        passed_count = sum(1 for meta in metas if meta.get("evaluation_passed") is True)

    return {
        "input": row,
        "output": outputs,
        "result": {
            "passed": passed_count,
            "failed": attempts - passed_count,
            "attempts": attempts,
        },
        "meta": metas,
    }


async def process_row(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    stats: Stats,
) -> Dict[str, Any]:
    if cfg.agentic:
        if cfg.multi_output:
            return await process_row_multi_agentic(session, cfg, row, index, stats)
        return await process_row_agentic(session, cfg, row, index, stats)

    if cfg.multi_output:
        return await process_row_multi(session, cfg, row, index, stats)

    messages = build_messages(cfg, row, index)
    metas: List[Dict[str, Any]] = []
    attempts = 0
    payload: Any = None
    extracted: Optional[str] = None
    passed: Optional[bool] = None
    score: Optional[float] = None
    schema_valid: Optional[bool] = None
    schema_error: Optional[str] = None
    is_judge = cfg.evaluation is not None and cfg.evaluation.type == "llm_judge"

    for _ in range(cfg.max_attempts):
        attempts += 1
        call = await call_api(session, cfg, messages, stats)
        meta = dict(call.meta)
        if not call.ok:
            metas.append(meta)
            payload = None
            extracted = None
            score = None
            if cfg.output_schema is not None:
                schema_valid = False
                schema_error = "Invalid JSON: no response (%s)" % (
                    call.error or "request failed"
                )
                passed = False
            else:
                passed = None if cfg.evaluation is None else False
            break

        # Schema validation runs before any other evaluation.
        ok, value, error = check_output_schema(cfg, call.content)
        if not ok:
            metas.append(meta)
            schema_valid = False
            schema_error = error
            payload = None
            extracted = None
            score = None
            passed = False
            if cfg.scheme == "rejection":
                continue  # a failed attempt; try again
            break
        if cfg.output_schema is not None:
            schema_valid = True
            schema_error = None

        if cfg.evaluation is None:
            metas.append(meta)
            payload = value
            extracted = None
            passed = True if cfg.output_schema is not None else None
            break

        attempt_passed, attempt_extracted, extra = await evaluate_response(
            session, cfg, row, index, call.content, stats
        )
        if "judge_meta" in extra:
            meta["judge_meta"] = extra["judge_meta"]
        metas.append(meta)
        attempt_score = extra.get("judge_score")

        if attempt_passed:
            payload = value
            extracted = attempt_extracted
            score = attempt_score
            passed = True
            break

        # Failed evaluation: keep the response for non-rejection schemes.
        if cfg.scheme != "rejection":
            payload = value
            extracted = attempt_extracted
            score = attempt_score
            passed = False
            break

        payload = None
        extracted = None
        score = None
        passed = False

    output = None if payload is None else {cfg.output_field: payload}
    if output is None:
        extracted = None
        score = None

    result: Dict[str, Any] = {
        "passed": passed,
        "extracted_answer": extracted,
        "attempts": attempts,
    }
    if is_judge:
        result["judge_score"] = _json_number(score)
    _apply_schema_result(cfg, result, schema_valid, schema_error)

    return {
        "input": row,
        "output": output,
        "result": result,
        "meta": metas[0] if len(metas) == 1 else metas,
    }


def build_cost_tracker(configs: Sequence[TaskConfig]) -> CostTracker:
    """One tracker for the whole run; costs accumulate across every task."""
    enabled = any(cfg.cost_configured for cfg in configs)
    budgets = [cfg.budget for cfg in configs if cfg.budget is not None]
    tracker = CostTracker(enabled=enabled, budget=min(budgets) if budgets else None)
    for cfg in configs:
        cfg.cost_tracker = tracker
    return tracker


def _row_verdict(result: Dict[str, Any]) -> Optional[bool]:
    """Pass/fail for one written row, as the progress counters see it."""
    outcome = result.get("result", {}).get("passed")
    if isinstance(result.get("output"), list):
        return bool(outcome)
    if outcome is True:
        return True
    if outcome is False:
        return False
    return None


def _leading_results(
    results: Sequence[Optional[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """Completed rows, as a prefix: a gap ends the file (budget stop)."""
    out: List[Dict[str, Any]] = []
    for result in results:
        if result is None:
            break
        out.append(result)
    return out


async def _run_one_row(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    rows: List[Dict[str, Any]],
    index: int,
    stats: Stats,
    sink: List[Optional[Dict[str, Any]]],
    progress: Optional[ProgressReporter],
) -> bool:
    """Process one row; False means the budget stopped the run."""
    if cfg.cost_tracker.exhausted():
        return False
    try:
        result = await process_row(session, cfg, rows[index], index, stats)
    except BudgetExceeded:
        return False
    sink[index] = result
    if progress is not None:
        progress.note_row(_row_verdict(result))
    return True


async def run_task(
    cfg: TaskConfig,
    rows: List[Dict[str, Any]],
    stats: Stats,
    progress: Optional[ProgressReporter] = None,
) -> List[Dict[str, Any]]:
    results: List[Optional[Dict[str, Any]]] = [None] * len(rows)
    if not rows:
        return []

    queue: "asyncio.Queue[int]" = asyncio.Queue()
    for index in range(len(rows)):  # dispatched in input order
        queue.put_nowait(index)

    worker_count = max(1, min(cfg.concurrency, len(rows)))
    connector = aiohttp.TCPConnector(limit=worker_count, limit_per_host=worker_count)
    timeout = aiohttp.ClientTimeout(total=cfg.timeout, connect=60, sock_connect=60)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:

        async def worker() -> None:
            while True:
                try:
                    index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                if not await _run_one_row(
                    session, cfg, rows, index, stats, results, progress
                ):
                    return  # budget reached: stop scheduling new requests

        await asyncio.gather(*(worker() for _ in range(worker_count)))

    return _leading_results(results)


async def run_rows(
    cfg: TaskConfig, rows: List[Dict[str, Any]], progress: Optional[ProgressReporter] = None
) -> Tuple[List[Dict[str, Any]], Stats]:
    stats = Stats()
    cfg.progress = progress
    if progress is not None:
        progress.start()
    try:
        results = await run_task(cfg, rows, stats, progress)
    finally:
        if progress is not None:
            await progress.stop()
            progress.emit(final=True)
    return results, stats


async def run_tasks(
    jobs: List[Tuple[TaskConfig, List[Dict[str, Any]]]],
    progress: Optional[ProgressReporter] = None,
) -> List[Tuple[TaskConfig, List[Dict[str, Any]], Stats]]:
    """Run every task concurrently; requests interleave across tasks."""
    for cfg, _rows in jobs:
        cfg.progress = progress
    if progress is not None:
        progress.start()
    try:
        return await _run_tasks(jobs, progress)
    finally:
        if progress is not None:
            await progress.stop()
            progress.emit(final=True)


async def _run_tasks(
    jobs: List[Tuple[TaskConfig, List[Dict[str, Any]]]],
    progress: Optional[ProgressReporter] = None,
) -> List[Tuple[TaskConfig, List[Dict[str, Any]], Stats]]:
    stats_list = [Stats() for _ in jobs]
    results: List[List[Optional[Dict[str, Any]]]] = [
        [None] * len(rows) for _cfg, rows in jobs
    ]

    # Round robin over the tasks so the first rows of every task go out
    # together; within a task, rows are still dispatched in input order.
    order: List[Tuple[int, int]] = []
    depth = max([len(rows) for _cfg, rows in jobs] or [0])
    for position in range(depth):
        for task_index, (_cfg, rows) in enumerate(jobs):
            if position < len(rows):
                order.append((task_index, position))

    if not order:
        return [(cfg, [], stats) for (cfg, _rows), stats in zip(jobs, stats_list)]

    queue: "asyncio.Queue[Tuple[int, int]]" = asyncio.Queue()
    for item in order:
        queue.put_nowait(item)

    async with contextlib.AsyncExitStack() as stack:
        sessions: List[aiohttp.ClientSession] = []
        worker_count = 0
        for cfg, rows in jobs:
            count = max(1, min(cfg.concurrency, len(rows))) if rows else 1
            worker_count += count if rows else 0
            connector = aiohttp.TCPConnector(limit=count, limit_per_host=count)
            timeout = aiohttp.ClientTimeout(total=cfg.timeout, connect=60, sock_connect=60)
            sessions.append(
                await stack.enter_async_context(
                    aiohttp.ClientSession(connector=connector, timeout=timeout)
                )
            )

        worker_count = max(1, min(worker_count, len(order)))

        async def worker() -> None:
            while True:
                try:
                    task_index, row_index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                cfg, rows = jobs[task_index]
                if not await _run_one_row(
                    sessions[task_index],
                    cfg,
                    rows,
                    row_index,
                    stats_list[task_index],
                    results[task_index],
                    progress,
                ):
                    return  # budget reached: stop scheduling new requests

        await asyncio.gather(*(worker() for _ in range(worker_count)))

    return [
        (cfg, _leading_results(results[task_index]), stats_list[task_index])
        for task_index, (cfg, _rows) in enumerate(jobs)
    ]


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def write_results(
    path: str, results: List[Dict[str, Any]], append: bool = False
) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, "a" if append else "w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# Resume
# --------------------------------------------------------------------------- #


def _resume_row_incomplete(row: Dict[str, Any], cfg: TaskConfig) -> bool:
    """True when a previously written row must be produced again."""
    output = row.get("output")
    if isinstance(output, list):
        # Multi-solution row: fewer solutions than asked for means unfinished.
        return len(output) < cfg.num_solutions
    if cfg.scheme == "rejection":
        # A rejection row without a kept solution never reached num_solutions.
        return output is None
    return False


def resume_skip_count(path: str, cfg: TaskConfig) -> int:
    """How many leading input rows an existing output file already covers."""
    if not path or not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = [line for line in handle.read().splitlines() if line.strip()]
    except OSError:
        return 0
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except ValueError:
            return index  # a half-written line ends the usable prefix
        if not isinstance(row, dict) or _resume_row_incomplete(row, cfg):
            return index
    return len(lines)


def truncate_output(path: str, keep_lines: int) -> None:
    """Drop everything after the first ``keep_lines`` rows of an output file."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = [line for line in handle.read().splitlines() if line.strip()]
    except OSError:
        return
    if len(lines) == keep_lines:
        return
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines[:keep_lines]:
            handle.write(line + "\n")


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


def estimate_task(cfg: TaskConfig, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Token/cost/time estimate for one task without calling the API."""
    inputs = len(rows)
    words = 0
    setup = cfg.icl_setups[0] if cfg.icl_setups else None
    for index, row in enumerate(rows):
        messages = build_messages(cfg, row, index, setup)
        if cfg.api_type == "completions":
            words += count_words(
                render_chat_prompt(cfg.chat_template, messages, cfg.tools or None)
            )
        else:
            words += messages_word_count(messages)
    average_words = (words / inputs) if inputs else 0.0
    prompt_tokens = int(round(average_words * DRY_RUN_TOKENS_PER_WORD * inputs))
    completion_tokens = cfg.max_tokens * inputs
    # Cost is derived from the reported token counts so the numbers agree.
    cost = (prompt_tokens / 1000.0) * cfg.prompt_rate + (
        completion_tokens / 1000.0
    ) * cfg.completion_rate
    return {
        "inputs": inputs,
        "est_prompt_tokens": prompt_tokens,
        "est_completion_tokens": completion_tokens,
        "est_total_tokens": prompt_tokens + completion_tokens,
        "est_cost": _round_cost(cost),
    }


def build_dry_run_summary(
    jobs: Sequence[Tuple[TaskConfig, List[Dict[str, Any]]]]
) -> Dict[str, Any]:
    tasks: Dict[str, Any] = {}
    total_inputs = 0
    total_tokens = 0
    total_cost = 0.0
    total_minutes = 0.0
    for cfg, rows in jobs:
        estimate = estimate_task(cfg, rows)
        tasks[cfg.name] = estimate
        total_inputs += estimate["inputs"]
        total_tokens += estimate["est_total_tokens"]
        total_cost += estimate["est_cost"]
        if cfg.rpm:
            total_minutes += estimate["inputs"] * cfg.avg_attempts() / float(cfg.rpm)
    return {
        "tasks": tasks,
        "total_inputs": total_inputs,
        "est_total_tokens": total_tokens,
        "est_total_cost": _round_cost(total_cost),
        "est_time_minutes": _round_cost(total_minutes),
    }


def _iter_call_metas(meta: Any) -> Iterator[Dict[str, Any]]:
    entries = meta if isinstance(meta, list) else [meta]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        yield entry
        judge_meta = entry.get("judge_meta")
        if isinstance(judge_meta, dict):
            yield judge_meta


class Tally:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.solutions = 0


def _tally(results: List[Dict[str, Any]]) -> Tally:
    tally = Tally()
    for result in results:
        outcome = result["result"]["passed"]
        output = result["output"]
        if isinstance(output, list):
            # Part 3 list format: a row counts as passed when it produced at
            # least one solution that was kept.
            tally.solutions += len(output)
            if outcome:
                tally.passed += 1
            else:
                tally.failed += 1
        else:
            has_output = output is not None
            tally.solutions += 1 if has_output else 0
            if outcome is True or (outcome is None and has_output):
                tally.passed += 1
            if outcome is False or not has_output:
                tally.failed += 1
        for entry in _iter_call_metas(result["meta"]):
            if "iterations_detail" in entry:
                # Agentic metadata is already aggregated over the loop.
                tally.prompt_tokens += int(entry.get("total_prompt_tokens") or 0)
                tally.completion_tokens += int(
                    entry.get("total_completion_tokens") or 0
                )
                continue
            tally.prompt_tokens += int(entry.get("prompt_tokens") or 0)
            tally.completion_tokens += int(entry.get("completion_tokens") or 0)
    return tally


def build_summary(
    results: List[Dict[str, Any]],
    stats: Stats,
    cost: Optional[CostTracker] = None,
    resumed_from: Optional[int] = None,
) -> Dict[str, Any]:
    tally = _tally(results)
    elapsed = stats.elapsed
    throughput = (stats.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0

    summary: Dict[str, Any] = {"total": len(results)}
    if resumed_from is not None:
        summary["resumed_from"] = resumed_from
    summary.update(
        {
            "passed": tally.passed,
            "failed": tally.failed,
            "total_prompt_tokens": tally.prompt_tokens,
            "total_completion_tokens": tally.completion_tokens,
            "total_api_calls": stats.api_calls,
            "elapsed_seconds": round(elapsed, 1),
            "throughput_rpm": round(throughput, 1),
        }
    )
    if cost is not None and cost.enabled:
        summary["cost"] = cost.summary()
    return summary


def build_multi_summary(
    executed: List[Tuple[TaskConfig, List[Dict[str, Any]], Stats]],
    cost: Optional[CostTracker] = None,
    resumed: bool = False,
) -> Dict[str, Any]:
    overall = Stats()
    total = 0
    passed = 0
    failed = 0
    prompt_tokens = 0
    completion_tokens = 0
    tasks: Dict[str, Any] = {}

    for cfg, results, stats in executed:
        overall.merge(stats)
        tally = _tally(results)
        total += len(results)
        passed += tally.passed
        failed += tally.failed
        prompt_tokens += tally.prompt_tokens
        completion_tokens += tally.completion_tokens
        average = tally.solutions / len(results) if results else 0.0
        entry: Dict[str, Any] = {
            "total": len(results),
            "passed": tally.passed,
            "failed": tally.failed,
            "total_solutions": tally.solutions,
            "avg_solutions_per_input": round(average, 2),
            "total_api_calls": stats.api_calls,
        }
        if resumed:
            entry["resumed_from"] = cfg.resumed_from
        tasks[cfg.name] = entry

    elapsed = overall.elapsed
    throughput = (overall.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0

    summary: Dict[str, Any] = {"total": total}
    if resumed:
        summary["resumed_from"] = sum(cfg.resumed_from for cfg, _r, _s in executed)
    summary.update(
        {
            "passed": passed,
            "failed": failed,
            "total_prompt_tokens": prompt_tokens,
            "total_completion_tokens": completion_tokens,
            "total_api_calls": overall.api_calls,
            "elapsed_seconds": round(elapsed, 1),
            "throughput_rpm": round(throughput, 1),
        }
    )
    if cost is not None and cost.enabled:
        summary["cost"] = cost.summary()
    summary["tasks"] = tasks
    return summary


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class ArgumentParser(argparse.ArgumentParser):
    """argparse parser that exits 1 (config error) instead of 2 on bad usage."""

    def error(self, message: str) -> "None":  # type: ignore[override]
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="rejector.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run one or more tasks over JSONL inputs")
    run.add_argument(
        "--input",
        action="append",
        default=None,
        help="JSONL input file, or <task>=<path> for a multi-task config",
    )
    run.add_argument(
        "--input-dir",
        dest="input_dir",
        default=None,
        help="directory holding <task_name>.jsonl for a multi-task config",
    )
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--output", required=True, help="JSONL output file or directory")
    run.add_argument(
        "--task",
        dest="tasks",
        action="append",
        default=None,
        help="run only this task (repeatable)",
    )
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument(
        "--eval-model",
        dest="eval_model",
        default=None,
        help="override the judge model for llm_judge tasks",
    )
    run.add_argument("--rpm", default=None)
    run.add_argument("--tpm", default=None, help="sliding 60s token budget")
    run.add_argument(
        "--max-concurrent",
        dest="max_concurrent",
        default=None,
        help="hard cap on in-flight API requests",
    )
    run.add_argument(
        "--budget", default=None, help="stop sending requests once cost reaches this"
    )
    run.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="skip input rows already present in the output file",
    )
    run.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="validate config and inputs, print an estimate, make no API calls",
    )
    run.add_argument(
        "--progress",
        action="store_true",
        default=False,
        help="print progress updates to stderr",
    )
    run.add_argument(
        "--api-type",
        dest="api_type",
        default=None,
        choices=list(API_TYPES),
        help="chat completions or raw completions endpoint",
    )
    run.add_argument(
        "--chat-template",
        dest="chat_template",
        default=None,
        choices=list(CHAT_TEMPLATES),
        help="prompt template used to render conversations in completions mode",
    )
    run.add_argument(
        "--max-iterations",
        dest="max_iterations",
        default=None,
        help="API requests allowed in one agentic loop",
    )
    run.add_argument("--max-tokens", dest="max_tokens", default=None)
    run.add_argument("--scheme", default=None, choices=list(SCHEMES))
    run.add_argument("--temperature", default=None)
    run.add_argument("--n", default=None)
    run.add_argument(
        "--num-solutions",
        dest="num_solutions",
        default=None,
        help="number of solutions to collect per input",
    )
    run.add_argument(
        "--icl-strategy",
        dest="icl_strategy",
        default=None,
        choices=list(ICL_STRATEGIES),
        help="how to pick an ICL setup for each attempt",
    )
    run.add_argument(
        "--icl-k",
        dest="icl_k",
        default=None,
        help="number of in-context examples to use from the selected setup",
    )
    run.add_argument("--concurrency", default=None, help=argparse.SUPPRESS)
    return parser


def split_input_spec(spec: str) -> Tuple[Optional[str], str]:
    """Split `name=path` into (name, path); plain paths give (None, path)."""
    head, sep, tail = spec.partition("=")
    if not sep:
        return None, spec
    if not head.strip():
        return None, spec
    return head.strip(), tail


def resolve_single_input(args: argparse.Namespace, cfg: TaskConfig) -> str:
    inputs = args.input or []
    if args.input_dir is not None:
        if inputs:
            raise ConfigError("--input and --input-dir cannot be combined")
        path = os.path.join(args.input_dir, "%s.jsonl" % cfg.name)
        if not os.path.exists(path):
            raise ConfigError("input file not found: %s" % path)
        return path
    if not inputs:
        raise ConfigError("--input is required")
    if len(inputs) > 1:
        raise ConfigError("--input may only be given once for a single-task config")
    name, path = split_input_spec(inputs[0])
    if name is not None and name != cfg.name:
        # A plain path that happens to contain '=' is still a path.
        path = inputs[0]
    return path


def multi_task_names(path: str) -> List[str]:
    """Every task name defined by a multi-task config, selected or not."""
    raw = read_config_file(path)
    tasks = raw.get("tasks")
    if not isinstance(tasks, dict):
        return []
    return [str(name) for name in tasks]


def resolve_multi_inputs(
    args: argparse.Namespace, configs: List[TaskConfig], all_names: Sequence[str]
) -> Dict[str, str]:
    """Map each selected task to its input file.

    Unselected tasks are ignored: their inputs are neither required nor read.
    """
    names = [cfg.name for cfg in configs]
    inputs = args.input or []

    if inputs and args.input_dir is not None:
        raise ConfigError(
            "--input and --input-dir are alternative modes; do not combine them"
        )

    mapping: Dict[str, str] = {}

    if args.input_dir is not None:
        if not os.path.isdir(args.input_dir):
            raise ConfigError("input directory not found: %s" % args.input_dir)
        for name in names:
            path = os.path.join(args.input_dir, "%s.jsonl" % name)
            if not os.path.exists(path):
                raise ConfigError("input file not found for task %r: %s" % (name, path))
            mapping[name] = path
        return mapping

    if not inputs:
        raise ConfigError("--input <task>=<path> or --input-dir is required")

    known = set(all_names)
    selected = set(names)
    for spec in inputs:
        name, path = split_input_spec(spec)
        if name is None:
            raise ConfigError(
                "--input must be given as <task>=<path> for a multi-task config, got %r"
                % spec
            )
        if name not in known:
            raise ConfigError("unknown task %r in --input %r" % (name, spec))
        if name in selected:
            mapping[name] = path

    for name in names:
        if name not in mapping:
            raise ConfigError("no input file given for task %r" % name)
    return mapping


def prepare_output_dir(path: str) -> str:
    if os.path.exists(path) and not os.path.isdir(path):
        raise ConfigError("--output must be a directory for a multi-task config: %s" % path)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise ConfigError("could not create output directory %s: %s" % (path, exc))
    return path


def run_single(args: argparse.Namespace) -> int:
    resume = bool(_arg(args, "resume"))
    try:
        cfg = load_config(args.config, args)
        if args.tasks:
            unknown = [name for name in args.tasks if name != cfg.name]
            if unknown:
                raise ConfigError(
                    "unknown task %r; config defines: %s" % (unknown[0], cfg.name)
                )
        input_path = resolve_single_input(args, cfg)
        cfg.input_path = input_path
        cfg.output_path = args.output
        rows = load_rows(input_path)
        validate_rows(cfg, rows)
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    if _arg(args, "dry_run"):
        try:
            estimate = build_dry_run_summary([(cfg, rows)])
        except ConfigError as exc:
            sys.stderr.write("error: %s\n" % exc)
            return EXIT_ERROR
        sys.stdout.write(json.dumps(estimate) + "\n")
        return EXIT_OK

    skip = 0
    if resume:
        skip = min(resume_skip_count(args.output, cfg), len(rows))
        cfg.resumed_from = skip
        rows = rows[skip:]

    tracker = build_cost_tracker([cfg])
    progress = (
        ProgressReporter(len(rows), cfg.evaluation is not None, tracker)
        if _arg(args, "progress")
        else None
    )

    try:
        results, stats = asyncio.run(run_rows(cfg, rows, progress))
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    try:
        if resume:
            truncate_output(args.output, skip)
        write_results(args.output, results, append=resume)
    except OSError as exc:
        sys.stderr.write("error: could not write output %s: %s\n" % (args.output, exc))
        return EXIT_ERROR

    summary = build_summary(
        results, stats, tracker, resumed_from=skip if resume else None
    )
    sys.stdout.write(json.dumps(summary) + "\n")
    return EXIT_OK


def run_multi(args: argparse.Namespace) -> int:
    resume = bool(_arg(args, "resume"))
    dry_run = bool(_arg(args, "dry_run"))
    try:
        selected = args.tasks or None
        all_names = multi_task_names(args.config)
        configs = load_multi_config(args.config, args, selected)
        if not configs:
            raise ConfigError("no tasks selected")
        inputs = resolve_multi_inputs(args, configs, all_names)
        output_dir = args.output if dry_run else prepare_output_dir(args.output)

        jobs: List[Tuple[TaskConfig, List[Dict[str, Any]]]] = []
        for cfg in configs:
            cfg.input_path = inputs[cfg.name]
            cfg.output_path = os.path.join(output_dir, "%s.jsonl" % cfg.name)
            rows = load_rows(cfg.input_path)
            validate_rows(cfg, rows)
            jobs.append((cfg, rows))
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    if dry_run:
        try:
            estimate = build_dry_run_summary(jobs)
        except ConfigError as exc:
            sys.stderr.write("error: %s\n" % exc)
            return EXIT_ERROR
        sys.stdout.write(json.dumps(estimate) + "\n")
        return EXIT_OK

    if resume:
        # Resume is decided per task, against that task's own output file.
        trimmed: List[Tuple[TaskConfig, List[Dict[str, Any]]]] = []
        for cfg, rows in jobs:
            skip = min(resume_skip_count(cfg.output_path or "", cfg), len(rows))
            cfg.resumed_from = skip
            trimmed.append((cfg, rows[skip:]))
        jobs = trimmed

    tracker = build_cost_tracker(configs)
    progress = (
        ProgressReporter(
            sum(len(rows) for _cfg, rows in jobs),
            any(cfg.evaluation is not None for cfg in configs),
            tracker,
        )
        if _arg(args, "progress")
        else None
    )

    try:
        executed = asyncio.run(run_tasks(jobs, progress))
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    for cfg, results, _stats in executed:
        try:
            if resume:
                truncate_output(cfg.output_path or "", cfg.resumed_from)
            write_results(cfg.output_path or "", results, append=resume)
        except OSError as exc:
            sys.stderr.write(
                "error: could not write output %s: %s\n" % (cfg.output_path, exc)
            )
            return EXIT_ERROR

    sys.stdout.write(
        json.dumps(build_multi_summary(executed, tracker, resume)) + "\n"
    )
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        raw = read_config_file(args.config)
        multi = is_multi_task(raw)
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    return run_multi(args) if multi else run_single(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(EXIT_ERROR)
