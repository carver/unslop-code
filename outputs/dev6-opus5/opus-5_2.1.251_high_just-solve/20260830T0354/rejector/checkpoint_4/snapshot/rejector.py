#!/usr/bin/env python3
"""rejector - run prompts from JSONL files against an OpenAI-compatible API.

Usage:
    python rejector.py run --config task.yaml --input data.jsonl --output out.jsonl
    python rejector.py run --config multi.yaml --input-dir data/ --output results/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import shlex
import signal
import sys
import time

MAX_HTTP_RETRIES = 3          # retries after the initial request (4 calls total)
RETRY_BACKOFF_BASE = 0.05     # seconds; doubled per retry
DEFAULT_CONCURRENCY_CAP = 512


def _bootstrap_venv() -> None:
    """Re-exec inside the project virtualenv when dependencies are missing."""
    if os.environ.get("REJECTOR_NO_BOOTSTRAP"):
        return
    try:
        import yaml  # noqa: F401
        return
    except ImportError:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(here, ".venv", "bin", "python"),
                      os.path.join(here, "venv", "bin", "python")):
        if os.path.exists(candidate) and os.path.realpath(candidate) != os.path.realpath(sys.executable):
            os.environ["REJECTOR_NO_BOOTSTRAP"] = "1"
            try:
                os.execv(candidate, [candidate, os.path.abspath(__file__)] + sys.argv[1:])
            except OSError:
                return


_bootstrap_venv()

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - fallback parser is used instead
    yaml = None


class ConfigError(Exception):
    """Configuration or input problem -> exit code 1."""


# --------------------------------------------------------------------------
# YAML loading
# --------------------------------------------------------------------------

def load_yaml(text: str):
    if yaml is not None:
        return yaml.safe_load(text)
    return _MiniYAML(text).parse()


class _MiniYAML:
    """Very small YAML subset parser, used only when PyYAML is unavailable.

    Supports nested mappings, block sequences, flow sequences of scalars,
    block scalars (| and >) and the usual scalar types.
    """

    def __init__(self, text: str):
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.i = 0

    # -- line helpers -----------------------------------------------------
    def _indent(self, line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def _is_skippable(self, line: str) -> bool:
        s = line.strip()
        return not s or s.startswith("#") or s in ("---", "...")

    def _peek(self):
        while self.i < len(self.lines) and self._is_skippable(self.lines[self.i]):
            self.i += 1
        if self.i >= len(self.lines):
            return None, None
        line = self.lines[self.i]
        return self._indent(line), self._strip_comment(line.strip())

    @staticmethod
    def _strip_comment(s: str) -> str:
        out = []
        quote = None
        prev = ""
        for ch in s:
            if quote:
                out.append(ch)
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
                out.append(ch)
            elif ch == "#" and (prev == "" or prev.isspace()):
                break
            else:
                out.append(ch)
            prev = ch
        return "".join(out).rstrip()

    # -- parsing ----------------------------------------------------------
    def parse(self):
        indent, _ = self._peek()
        if indent is None:
            return None
        return self._parse_block(indent)

    def _parse_block(self, indent: int):
        cur, content = self._peek()
        if cur is None or cur < indent:
            return None
        if content == "-" or content.startswith("- "):
            return self._parse_seq(cur)
        return self._parse_map(cur)

    def _parse_seq(self, indent: int):
        items = []
        while True:
            cur, content = self._peek()
            if cur is None or cur < indent or not (content == "-" or content.startswith("- ")):
                return items
            rest = content[1:].strip()
            self.i += 1
            if not rest:
                nxt, _ = self._peek()
                if nxt is not None and nxt > indent:
                    items.append(self._parse_block(nxt))
                else:
                    items.append(None)
            elif re.match(r"^[^\s:]+\s*:(\s|$)", rest) or re.match(r"^(\"[^\"]*\"|'[^']*')\s*:(\s|$)", rest):
                # inline mapping start inside a sequence item
                self.lines[self.i - 1] = " " * (indent + 2) + rest
                self.i -= 1
                items.append(self._parse_map(indent + 2))
            else:
                items.append(self._scalar(rest))

    def _parse_map(self, indent: int):
        result = {}
        while True:
            cur, content = self._peek()
            if cur is None or cur < indent:
                return result
            if cur > indent:
                raise ConfigError("invalid YAML indentation near: %r" % content)
            m = re.match(r"^(\"[^\"]*\"|'[^']*'|[^:]+?)\s*:(?:\s+(.*))?$", content)
            if not m:
                raise ConfigError("cannot parse YAML line: %r" % content)
            key = self._scalar(m.group(1))
            rest = (m.group(2) or "").strip()
            self.i += 1
            if rest.startswith("|") or rest.startswith(">"):
                result[key] = self._block_scalar(rest, indent)
            elif rest:
                result[key] = self._scalar(rest)
            else:
                nxt, _ = self._peek()
                if nxt is not None and nxt > indent:
                    result[key] = self._parse_block(nxt)
                else:
                    result[key] = None

    def _block_scalar(self, header: str, indent: int) -> str:
        folded = header[0] == ">"
        chomp = "clip"
        if "-" in header:
            chomp = "strip"
        elif "+" in header:
            chomp = "keep"
        body = []
        block_indent = None
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.strip():
                ind = self._indent(line)
                if ind <= indent:
                    break
                if block_indent is None:
                    block_indent = ind
                body.append(line[block_indent:] if len(line) >= block_indent else line.lstrip())
            else:
                body.append("")
            self.i += 1
        while body and not body[-1].strip():
            body.pop()
        if folded:
            out, buf = [], []
            for ln in body:
                if ln.strip():
                    buf.append(ln.strip())
                else:
                    out.append(" ".join(buf))
                    buf = []
                    out.append("")
            if buf:
                out.append(" ".join(buf))
            text = "\n".join(out)
        else:
            text = "\n".join(body)
        if chomp == "strip":
            return text
        return text + "\n" if text else text

    def _scalar(self, s: str):
        s = s.strip()
        if not s:
            return None
        if s[0] == '"' and s[-1] == '"' and len(s) >= 2:
            return self._unescape(s[1:-1])
        if s[0] == "'" and s[-1] == "'" and len(s) >= 2:
            return s[1:-1].replace("''", "'")
        if s.startswith("[") and s.endswith("]"):
            inner = s[1:-1].strip()
            if not inner:
                return []
            return [self._scalar(p) for p in self._split_flow(inner)]
        if s.startswith("{") and s.endswith("}"):
            inner = s[1:-1].strip()
            out = {}
            if inner:
                for part in self._split_flow(inner):
                    k, _, v = part.partition(":")
                    out[self._scalar(k)] = self._scalar(v)
            return out
        low = s.lower()
        if low in ("null", "~", "none"):
            return None
        if low in ("true", "yes", "on"):
            return True
        if low in ("false", "no", "off"):
            return False
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        return s

    @staticmethod
    def _split_flow(s: str):
        parts, buf, quote, depth = [], [], None, 0
        for ch in s:
            if quote:
                buf.append(ch)
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
                buf.append(ch)
            elif ch in "[{":
                depth += 1
                buf.append(ch)
            elif ch in "]}":
                depth -= 1
                buf.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        if buf:
            parts.append("".join(buf).strip())
        return [p for p in parts if p != ""]

    @staticmethod
    def _unescape(s: str) -> str:
        out, i = [], 0
        mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "0": "\0", "/": "/"}
        while i < len(s):
            if s[i] == "\\" and i + 1 < len(s):
                out.append(mapping.get(s[i + 1], s[i + 1]))
                i += 2
            else:
                out.append(s[i])
                i += 1
        return "".join(out)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

VALID_SCHEMES = ("greedy", "sample", "rejection", "agentic")
VALID_EVAL_TYPES = ("exact_match", "contains", "regex", "llm_judge", "script")
VALID_EXTRACTS = ("last_number", "last_line", "full", "letter", "first_number")
VALID_ICL_STRATEGIES = ("fixed", "random", "round_robin")
VALID_API_TYPES = ("chat", "completions")
VALID_CHAT_TEMPLATES = ("chatml", "llama3", "mistral", "zephyr")
VALID_HANDLER_TYPES = ("echo", "static_map", "script")

RESPONSE_KEY = "__response__"
SCRIPT_TIMEOUT = 10.0          # seconds; a timeout is a failed evaluation
SCRIPT_KILL_GRACE = 5.0        # seconds to drain output after killing a script
MAX_SCRIPT_CONCURRENCY = 64
DEFAULT_MAX_ITERATIONS = 10    # agentic API requests per loop
TOOL_TIMEOUT = 10.0            # seconds a `script` tool handler may run
DEFAULT_STATIC_MAP_MISS = "NOT_FOUND"


def deep_merge(base, override):
    """Merge `override` onto `base`; nested mappings merge key by key."""
    if not isinstance(base, dict):
        return override
    if not isinstance(override, dict):
        return override if override is not None else base
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Config:
    """One fully resolved task (defaults already merged in)."""

    def __init__(self, task: dict, overrides: dict, name=None, prefix="task",
                 config_dir=None):
        if task is None:
            raise ConfigError("config file is empty")
        if not isinstance(task, dict):
            raise ConfigError("%s must be a mapping" % prefix)
        self.raw = task
        self.prefix = prefix
        self.config_dir = config_dir or os.getcwd()
        self.name = name if name is not None else task.get("name")

        self.api_url = _first(overrides.get("api_url"), task.get("api_url"))
        if not isinstance(self.api_url, str) or not self.api_url.strip():
            raise ConfigError("%s.api_url is required (or pass --api-url)" % prefix)
        self.api_url = self.api_url.strip().rstrip("/")

        self.model = _first(overrides.get("model"), task.get("model"))
        if not isinstance(self.model, str) or not self.model.strip():
            raise ConfigError("%s.model is required (or pass --model)" % prefix)

        gen_section = task.get("generation") if isinstance(task.get("generation"), dict) else {}

        api_type = _first(overrides.get("api_type"), task.get("api_type"),
                          gen_section.get("api_type"), "chat")
        if api_type not in VALID_API_TYPES:
            raise ConfigError(
                "%s.api_type must be one of %s, got %r"
                % (prefix, ", ".join(VALID_API_TYPES), api_type))
        self.api_type = api_type

        chat_template = _first(overrides.get("chat_template"), task.get("chat_template"),
                               gen_section.get("chat_template"), "chatml")
        if chat_template not in VALID_CHAT_TEMPLATES:
            raise ConfigError(
                "%s.chat_template must be one of %s, got %r"
                % (prefix, ", ".join(VALID_CHAT_TEMPLATES), chat_template))
        self.chat_template = chat_template

        rpm = _first(overrides.get("rpm"), task.get("rpm"), 60)
        if isinstance(rpm, bool) or not isinstance(rpm, (int, float)):
            raise ConfigError("%s.rpm must be a number, got %r" % (prefix, rpm))
        if rpm <= 0:
            raise ConfigError("%s.rpm must be greater than 0, got %r" % (prefix, rpm))
        self.rpm = float(rpm)

        prompt = task.get("prompt")
        if not isinstance(prompt, dict):
            raise ConfigError("%s.prompt is required and must be a mapping" % prefix)
        self.system_prompt = prompt.get("system")
        self.user_prompt = prompt.get("user")
        if self.system_prompt is not None and not isinstance(self.system_prompt, str):
            raise ConfigError("%s.prompt.system must be a string" % prefix)
        if not isinstance(self.user_prompt, str) or not self.user_prompt:
            raise ConfigError("%s.prompt.user is required and must be a string" % prefix)

        gen = task.get("generation") or {}
        if not isinstance(gen, dict):
            raise ConfigError("%s.generation must be a mapping" % prefix)

        self.scheme = _first(overrides.get("scheme"), gen.get("scheme"), "greedy")
        if self.scheme not in VALID_SCHEMES:
            raise ConfigError(
                "%s.generation.scheme must be one of %s, got %r"
                % (prefix, ", ".join(VALID_SCHEMES), self.scheme))

        temperature = _first(overrides.get("temperature"), gen.get("temperature"), 0.0)
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise ConfigError("%s.generation.temperature must be a number, got %r"
                              % (prefix, temperature))
        self.temperature = float(temperature)

        max_tokens = _first(overrides.get("max_tokens"), gen.get("max_tokens"), 512)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, (int, float)):
            raise ConfigError("%s.generation.max_tokens must be an integer, got %r"
                              % (prefix, max_tokens))
        if int(max_tokens) <= 0:
            raise ConfigError("%s.generation.max_tokens must be greater than 0" % prefix)
        self.max_tokens = int(max_tokens)

        n = _first(overrides.get("n"), gen.get("n"), 1)
        if isinstance(n, bool) or not isinstance(n, (int, float)) or int(n) != n:
            raise ConfigError("%s.generation.n must be an integer, got %r" % (prefix, n))
        if int(n) < 1:
            raise ConfigError("%s.generation.n must be at least 1, got %r" % (prefix, n))
        self.n = int(n)

        if self.scheme == "greedy":
            self.temperature = 0.0
            self.n = 1
        elif self.scheme == "sample":
            if self.temperature <= 0:
                raise ConfigError(
                    "scheme 'sample' requires generation.temperature > 0, got %s" % self.temperature)
            self.n = 1
        elif self.scheme == "agentic":
            # The loop length is bounded by max_iterations, not by `n`.
            self.n = 1
        else:  # rejection
            if self.temperature <= 0:
                raise ConfigError(
                    "scheme 'rejection' requires generation.temperature > 0, got %s" % self.temperature)

        max_iterations = _first(overrides.get("max_iterations"), gen.get("max_iterations"),
                                task.get("max_iterations"), DEFAULT_MAX_ITERATIONS)
        if (isinstance(max_iterations, bool) or not isinstance(max_iterations, (int, float))
                or int(max_iterations) != max_iterations):
            raise ConfigError("%s.generation.max_iterations must be an integer, got %r"
                              % (prefix, max_iterations))
        if int(max_iterations) < 1:
            raise ConfigError("%s.generation.max_iterations must be at least 1, got %r"
                              % (prefix, max_iterations))
        self.max_iterations = int(max_iterations)

        self.tools = self._parse_tools(task.get("tools"), prefix)

        ev = task.get("evaluation")
        self.evaluation = None
        if ev is not None:
            if not isinstance(ev, dict):
                raise ConfigError("%s.evaluation must be a mapping" % prefix)
            self.evaluation = self._parse_evaluation(ev, prefix, overrides)
        elif self.scheme == "rejection":
            raise ConfigError("%s.evaluation is required for scheme 'rejection'" % prefix)

        output_field = task.get("output_field", "output")
        if not isinstance(output_field, str) or not output_field:
            raise ConfigError("%s.output_field must be a non-empty string" % prefix)
        self.output_field = output_field

        num_solutions = _first(overrides.get("num_solutions"), task.get("num_solutions"), 1)
        if (isinstance(num_solutions, bool) or not isinstance(num_solutions, (int, float))
                or int(num_solutions) != num_solutions):
            raise ConfigError("%s.num_solutions must be an integer, got %r"
                              % (prefix, num_solutions))
        if int(num_solutions) < 1:
            raise ConfigError("%s.num_solutions must be at least 1, got %r"
                              % (prefix, num_solutions))
        self.num_solutions = int(num_solutions)

        self.icl_setups, self.icl_strategy, self.icl_k = self._parse_icl(
            task.get("icl"), prefix, overrides, self.config_dir)

        max_attempts = gen.get("max_attempts")
        if max_attempts is None:
            self.max_attempts = 3 * self.num_solutions
        else:
            if (isinstance(max_attempts, bool) or not isinstance(max_attempts, (int, float))
                    or int(max_attempts) != max_attempts):
                raise ConfigError("%s.generation.max_attempts must be an integer, got %r"
                                  % (prefix, max_attempts))
            if int(max_attempts) < 1:
                raise ConfigError("%s.generation.max_attempts must be at least 1, got %r"
                                  % (prefix, max_attempts))
            self.max_attempts = int(max_attempts)

    # -- tools ------------------------------------------------------------
    @staticmethod
    def _parse_tools(tools, prefix):
        """Validate `task.tools` into a list of tool definitions."""
        if tools is None:
            return []
        if not isinstance(tools, list):
            raise ConfigError("%s.tools must be a list" % prefix)
        parsed = []
        seen = set()
        for index, raw in enumerate(tools):
            where = "%s.tools[%d]" % (prefix, index)
            if not isinstance(raw, dict):
                raise ConfigError("%s must be a mapping" % where)
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ConfigError("%s.name is required and must be a non-empty string" % where)
            name = name.strip()
            if name in seen:
                raise ConfigError("%s.name %r is defined more than once" % (where, name))
            seen.add(name)
            description = raw.get("description")
            if description is not None and not isinstance(description, str):
                raise ConfigError("%s.description must be a string" % where)
            parameters = raw.get("parameters")
            if parameters is None:
                parameters = {"type": "object", "properties": {}}
            if not isinstance(parameters, dict):
                raise ConfigError("%s.parameters must be a mapping" % where)
            handler = Config._parse_handler(raw.get("handler"), where, parameters)
            parsed.append({
                "name": name,
                "description": description,
                "parameters": parameters,
                "handler": handler,
            })
        return parsed

    @staticmethod
    def _parse_handler(handler, where, parameters):
        if not isinstance(handler, dict):
            raise ConfigError("%s.handler is required and must be a mapping" % where)
        htype = handler.get("type")
        if htype not in VALID_HANDLER_TYPES:
            raise ConfigError(
                "%s.handler.type must be one of %s, got %r"
                % (where, ", ".join(VALID_HANDLER_TYPES), htype))
        parsed = {"type": htype}
        if htype == "static_map":
            mapping = handler.get("mapping")
            if mapping is None:
                mapping = {}
            if not isinstance(mapping, dict):
                raise ConfigError("%s.handler.mapping must be a mapping" % where)
            default = handler.get("default")
            if default is None:
                default = DEFAULT_STATIC_MAP_MISS
            parsed["mapping"] = {str(k): v for k, v in mapping.items()}
            parsed["default"] = default
            parsed["key_field"] = _first_required_param(parameters)
        elif htype == "script":
            command = handler.get("command")
            if not isinstance(command, str) or not command.strip():
                raise ConfigError(
                    "%s.handler.command is required and must be a non-empty string "
                    "for handler type 'script'" % where)
            arg_field = handler.get("arg_field")
            if arg_field is None:
                arg_field = _first_required_param(parameters)
            if not isinstance(arg_field, str) or not arg_field.strip():
                raise ConfigError(
                    "%s.handler.arg_field is required and must be a non-empty string "
                    "for handler type 'script'" % where)
            parsed["command"] = command.strip()
            parsed["arg_field"] = arg_field.strip()
        return parsed

    @property
    def tools_enabled(self) -> bool:
        """True when tool definitions travel with the request."""
        return self.scheme == "agentic" and bool(self.tools)

    def tool_specs(self):
        """Tool definitions in the OpenAI `tools` shape."""
        specs = []
        for tool in self.tools:
            function = {"name": tool["name"]}
            if tool["description"] is not None:
                function["description"] = tool["description"]
            function["parameters"] = tool["parameters"]
            specs.append({"type": "function", "function": function})
        return specs

    # -- ICL --------------------------------------------------------------
    @property
    def icl_configured(self) -> bool:
        return bool(self.icl_setups)

    @property
    def list_format(self) -> bool:
        """True when the row format is the Part 3 list shape."""
        return self.icl_configured or self.num_solutions > 1

    @staticmethod
    def _parse_icl(icl, prefix, overrides, config_dir):
        """Return (setups, strategy, k). `setups` is [] when ICL is unused."""
        strategy = _first(overrides.get("icl_strategy"),
                          (icl or {}).get("strategy") if isinstance(icl, dict) else None,
                          "fixed")
        k = _first(overrides.get("icl_k"),
                   (icl or {}).get("k") if isinstance(icl, dict) else None)
        if icl is None:
            return [], "fixed", None
        if not isinstance(icl, dict):
            raise ConfigError("%s.icl must be a mapping" % prefix)
        if strategy not in VALID_ICL_STRATEGIES:
            raise ConfigError(
                "%s.icl.strategy must be one of %s, got %r"
                % (prefix, ", ".join(VALID_ICL_STRATEGIES), strategy))
        if k is not None:
            if isinstance(k, bool) or not isinstance(k, (int, float)) or int(k) != k:
                raise ConfigError("%s.icl.k must be an integer, got %r" % (prefix, k))
            if int(k) < 0:
                raise ConfigError("%s.icl.k must not be negative, got %r" % (prefix, k))
            k = int(k)

        raw_setups = icl.get("setups")
        if not isinstance(raw_setups, list) or not raw_setups:
            raise ConfigError("%s.icl.setups must be a non-empty list" % prefix)

        setups = []
        for index, raw in enumerate(raw_setups):
            if not isinstance(raw, dict):
                raise ConfigError("%s.icl.setups[%d] must be a mapping" % (prefix, index))
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ConfigError(
                    "%s.icl.setups[%d].name is required and must be a non-empty string"
                    % (prefix, index))
            has_examples = "examples" in raw
            has_file = "file" in raw
            if has_examples == has_file:
                raise ConfigError(
                    "%s.icl.setups[%d] (%r) must have exactly one of 'examples' or 'file'"
                    % (prefix, index, name))
            where = "%s.icl.setups[%d] (%r)" % (prefix, index, name)
            if has_examples:
                examples = _parse_icl_examples(raw.get("examples"), where)
            else:
                path = raw.get("file")
                if not isinstance(path, str) or not path.strip():
                    raise ConfigError("%s.file must be a non-empty string" % where)
                if not os.path.isabs(path):
                    path = os.path.join(config_dir, path)
                examples = _read_icl_file(path, where)
            if k is not None:
                examples = examples[:k]
            setups.append({"name": name, "examples": examples})
        return setups, strategy, k

    @property
    def eval_type(self):
        return self.evaluation["type"] if self.evaluation else None

    @staticmethod
    def _parse_evaluation(ev: dict, prefix: str, overrides: dict) -> dict:
        etype = ev.get("type")
        if etype not in VALID_EVAL_TYPES:
            raise ConfigError(
                "%s.evaluation.type must be one of %s, got %r"
                % (prefix, ", ".join(VALID_EVAL_TYPES), etype))
        answer_field = ev.get("answer_field")
        pattern = ev.get("pattern")
        default_extract = "first_number" if etype == "llm_judge" else "full"
        extract = ev.get("extract", default_extract)
        if extract is None:
            extract = default_extract
        if extract not in VALID_EXTRACTS:
            raise ConfigError(
                "%s.evaluation.extract must be one of %s, got %r"
                % (prefix, ", ".join(VALID_EXTRACTS), extract))
        if etype in ("exact_match", "contains"):
            if not isinstance(answer_field, str) or not answer_field:
                raise ConfigError(
                    "%s.evaluation.answer_field is required for type %r" % (prefix, etype))
        if etype == "regex":
            if not isinstance(pattern, str) or not pattern:
                raise ConfigError("%s.evaluation.pattern is required for type 'regex'" % prefix)
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError("%s.evaluation.pattern is not a valid regex: %s" % (prefix, exc))

        parsed = {
            "type": etype,
            "answer_field": answer_field if isinstance(answer_field, str) else None,
            "pattern": pattern,
            "extract": extract,
            "judge_system": None,
            "judge_user": None,
            "threshold": None,
            "judge_model": None,
            "command_template": None,
            "success_exit_code": 0,
        }

        if etype == "llm_judge":
            judge_prompt = ev.get("judge_prompt")
            if not isinstance(judge_prompt, dict):
                raise ConfigError(
                    "%s.evaluation.judge_prompt is required and must be a mapping "
                    "for type 'llm_judge'" % prefix)
            judge_system = judge_prompt.get("system")
            judge_user = judge_prompt.get("user")
            if judge_system is not None and not isinstance(judge_system, str):
                raise ConfigError("%s.evaluation.judge_prompt.system must be a string" % prefix)
            if not isinstance(judge_user, str) or not judge_user:
                raise ConfigError(
                    "%s.evaluation.judge_prompt.user is required and must be a string" % prefix)
            threshold = ev.get("threshold")
            if threshold is None:
                raise ConfigError(
                    "%s.evaluation.threshold is required for type 'llm_judge'" % prefix)
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                raise ConfigError(
                    "%s.evaluation.threshold must be a number, got %r" % (prefix, threshold))
            judge_model = _first(overrides.get("eval_model"), ev.get("model"))
            if judge_model is not None and (not isinstance(judge_model, str) or not judge_model.strip()):
                raise ConfigError("%s.evaluation.model must be a non-empty string" % prefix)
            parsed["judge_system"] = judge_system
            parsed["judge_user"] = judge_user
            parsed["threshold"] = float(threshold)
            parsed["judge_model"] = judge_model.strip() if isinstance(judge_model, str) else None

        if etype == "script":
            command_template = ev.get("command_template")
            if not isinstance(command_template, str) or not command_template.strip():
                raise ConfigError(
                    "%s.evaluation.command_template is required and must be a string "
                    "for type 'script'" % prefix)
            code = ev.get("success_exit_code", 0)
            if code is None:
                code = 0
            if isinstance(code, bool) or not isinstance(code, (int, float)) or int(code) != code:
                raise ConfigError(
                    "%s.evaluation.success_exit_code must be an integer, got %r" % (prefix, code))
            parsed["command_template"] = command_template
            parsed["success_exit_code"] = int(code)

        return parsed


def _first_required_param(parameters):
    """The first entry of `parameters.required`, else the first property name."""
    if isinstance(parameters, dict):
        required = parameters.get("required")
        if isinstance(required, list):
            for item in required:
                if isinstance(item, str) and item:
                    return item
        properties = parameters.get("properties")
        if isinstance(properties, dict):
            for key in properties:
                if isinstance(key, str) and key:
                    return key
    return None


def _first(*values):
    for v in values:
        if v is not None:
            return v
    return None


def _check_icl_example(obj, where: str) -> dict:
    """Validate one `{"input": <object>, "output": <string>}` example."""
    if not isinstance(obj, dict):
        raise ConfigError("%s must be a mapping with 'input' and 'output'" % where)
    if "input" not in obj:
        raise ConfigError("%s is missing the 'input' key" % where)
    if "output" not in obj:
        raise ConfigError("%s is missing the 'output' key" % where)
    example_input = obj["input"]
    example_output = obj["output"]
    if not isinstance(example_input, dict):
        raise ConfigError("%s: 'input' must be an object" % where)
    if not isinstance(example_output, str):
        raise ConfigError("%s: 'output' must be a string" % where)
    return {"input": example_input, "output": example_output}


def _parse_icl_examples(raw, where: str):
    if not isinstance(raw, list):
        raise ConfigError("%s.examples must be a list" % where)
    return [_check_icl_example(item, "%s.examples[%d]" % (where, i))
            for i, item in enumerate(raw)]


def _read_icl_file(path: str, where: str):
    """Load a JSONL file of ICL examples. Any problem is a ConfigError."""
    if not os.path.exists(path):
        raise ConfigError("%s: ICL example file not found: %s" % (where, path))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise ConfigError("%s: cannot read ICL example file %s: %s" % (where, path, exc))
    examples = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError as exc:
            raise ConfigError(
                "%s: invalid JSON on line %d of %s: %s" % (where, lineno, path, exc))
        examples.append(_check_icl_example(obj, "%s: line %d of %s" % (where, lineno, path)))
    return examples


class ConfigSet:
    """Either a Part 1 single-task config or a multi-task `tasks` config."""

    def __init__(self, data, overrides, selected=None, config_dir=None):
        if data is None:
            raise ConfigError("config file is empty")
        if not isinstance(data, dict):
            raise ConfigError("config root must be a mapping")
        self.config_dir = config_dir or os.getcwd()

        if "tasks" in data:
            self.multi = True
            self._load_multi(data, overrides, selected)
            return

        if "defaults" in data:
            raise ConfigError("config uses 'defaults' but has no 'tasks' mapping")

        self.multi = False
        task = data.get("task", data if "task" not in data else None)
        if not isinstance(task, dict):
            raise ConfigError("config must contain a 'task' mapping")
        config = Config(task, overrides, name=task.get("name"), prefix="task",
                        config_dir=self.config_dir)
        if selected:
            names = [config.name] if config.name else []
            for want in selected:
                if want not in names:
                    raise ConfigError(
                        "--task %r is not defined in the config (available: %s)"
                        % (want, ", ".join(names) if names else "none"))
        self.names = [config.name]
        self.configs = {config.name: config}
        self.order = [config.name]

    def _load_multi(self, data, overrides, selected):
        tasks = data.get("tasks")
        if not isinstance(tasks, dict) or not tasks:
            raise ConfigError("config 'tasks' must be a non-empty mapping")
        defaults = data.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise ConfigError("config 'defaults' must be a mapping")

        self.order = [str(name) for name in tasks.keys()]
        if selected:
            unknown = [t for t in selected if t not in self.order]
            if unknown:
                raise ConfigError(
                    "--task %r is not defined in the config (available: %s)"
                    % (unknown[0], ", ".join(self.order)))
            chosen = [name for name in self.order if name in selected]
        else:
            chosen = list(self.order)

        self.names = chosen
        self.configs = {}
        for name in chosen:
            body = tasks[name]
            if body is None:
                body = {}
            if not isinstance(body, dict):
                raise ConfigError("tasks.%s must be a mapping" % name)
            merged = deep_merge(defaults, body)
            self.configs[name] = Config(merged, overrides, name=name,
                                        prefix="tasks.%s" % name,
                                        config_dir=self.config_dir)


# --------------------------------------------------------------------------
# Prompt templating
# --------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_\-\.]*)\}")
_RESPONSE_PLACEHOLDER = re.compile(r"\{%s\}" % re.escape(RESPONSE_KEY))


def template_fields(template: str):
    if not template:
        return []
    return [m.group(1) for m in _PLACEHOLDER.finditer(template)]


def _render_value(value) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def render_template(template: str, row: dict) -> str:
    def repl(match):
        return _render_value(row[match.group(1)])

    return _PLACEHOLDER.sub(repl, template)


def render_example(template: str, mapping: dict) -> str:
    """Render an ICL example input. Fields the example omits render as empty,
    so a partially specified example never aborts a run."""
    def repl(match):
        key = match.group(1)
        if key not in mapping:
            return ""
        return _render_value(mapping[key])

    return _PLACEHOLDER.sub(repl, template)


def render_command(template: str, row: dict, response: str) -> str:
    """Render a script command, then resolve any `{__response__}` a row field
    expanded into (e.g. a `test_code` column that embeds the placeholder)."""
    context = dict(row)
    context[RESPONSE_KEY] = response
    rendered = render_template(template, context)
    return _RESPONSE_PLACEHOLDER.sub(lambda _m: response, rendered)


# --------------------------------------------------------------------------
# Chat templates (completions mode)
# --------------------------------------------------------------------------

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def _message_content(message) -> str:
    content = message.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return _render_value(content)


def _render_chatml(messages) -> str:
    parts = []
    for message in messages:
        parts.append("<|im_start|>%s\n%s<|im_end|>\n"
                     % (message.get("role", "user"), _message_content(message)))
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


def _render_llama3(messages) -> str:
    parts = ["<|begin_of_text|>"]
    for message in messages:
        parts.append("<|start_header_id|>%s<|end_header_id|>\n\n%s<|eot_id|>"
                     % (message.get("role", "user"), _message_content(message)))
    parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return "".join(parts)


def _render_zephyr(messages) -> str:
    parts = []
    for message in messages:
        parts.append("<|%s|>\n%s</s>\n"
                     % (message.get("role", "user"), _message_content(message)))
    parts.append("<|assistant|>\n")
    return "".join(parts)


def _render_mistral(messages) -> str:
    """Mistral has no system marker: system text folds into the next user turn."""
    parts = []
    pending_system = None
    for message in messages:
        role = message.get("role", "user")
        content = _message_content(message)
        if role == "system":
            pending_system = content if pending_system is None else pending_system + "\n\n" + content
        elif role == "assistant":
            parts.append(" %s</s>" % content)
        elif role == "tool":
            parts.append("[TOOL_RESULTS] %s [/TOOL_RESULTS]" % content)
        else:
            if pending_system is not None:
                content = pending_system + "\n\n" + content
                pending_system = None
            parts.append("[INST] %s [/INST]" % content)
    if pending_system is not None:
        parts.append("[INST] %s [/INST]" % pending_system)
    return "".join(parts)


CHAT_TEMPLATE_RENDERERS = {
    "chatml": _render_chatml,
    "llama3": _render_llama3,
    "mistral": _render_mistral,
    "zephyr": _render_zephyr,
}


def render_chat_template(name: str, messages) -> str:
    """Render a message list into a single prompt string for /v1/completions."""
    renderer = CHAT_TEMPLATE_RENDERERS.get(name)
    if renderer is None:
        raise ConfigError("unknown chat template %r" % name)
    return renderer(messages)


def render_tool_instructions(tools) -> str:
    """Describe the task's tools for completions mode, where there is no
    native `tools` field to carry them."""
    lines = ["You have access to the following tools:", ""]
    for tool in tools:
        spec = {"name": tool["name"]}
        if tool["description"] is not None:
            spec["description"] = tool["description"]
        spec["parameters"] = tool["parameters"]
        lines.append(json.dumps(spec, ensure_ascii=False, sort_keys=False))
    lines += [
        "",
        "To call a tool, reply with a block of exactly this form:",
        "<tool_call>",
        '{"name": "<tool name>", "arguments": {<arguments as JSON>}}',
        "</tool_call>",
        "",
        "You may emit several such blocks in one reply. When you are done "
        "calling tools, reply with the final answer as plain text and no "
        "<tool_call> block.",
    ]
    return "\n".join(lines)


def with_tool_instructions(messages, tools):
    """Fold the tool descriptions into the system message (completions mode)."""
    block = render_tool_instructions(tools)
    out = [dict(message) for message in messages]
    for message in out:
        if message.get("role") == "system":
            existing = _message_content(message)
            message["content"] = (existing + "\n\n" + block) if existing else block
            return out
    return [{"role": "system", "content": block}] + out


def parse_text_tool_calls(text: str):
    """Pull `<tool_call>{...}</tool_call>` blocks out of a completion."""
    calls = []
    for index, block in enumerate(TOOL_CALL_RE.findall(text or "")):
        try:
            obj = json.loads(block)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name")
        if not isinstance(name, str) or not name:
            continue
        calls.append({
            "id": obj.get("id") or "call_%d" % (index + 1),
            "type": "function",
            "function": {"name": name, "arguments": obj.get("arguments")},
        })
    return calls


def parse_tool_calls(message) -> list:
    """Normalise the `tool_calls` array of a chat response."""
    raw = message.get("tool_calls") if isinstance(message, dict) else None
    if not isinstance(raw, list):
        return []
    calls = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        calls.append({
            "id": item.get("id") or "call_%d" % (index + 1),
            "type": item.get("type") or "function",
            "function": {"name": name, "arguments": function.get("arguments")},
        })
    return calls


def parse_tool_arguments(arguments):
    """`function.arguments` is a JSON string; be tolerant of a plain object."""
    if isinstance(arguments, dict):
        return arguments
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# --------------------------------------------------------------------------
# Extraction and evaluation
# --------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")
_LETTER_RE = re.compile(r"(?<![A-Za-z0-9_])([A-D])(?![A-Za-z0-9_])")


def extract_answer(text: str, method: str):
    if text is None:
        return None
    if method == "full":
        return text.strip()
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return ""
    if method == "last_number":
        matches = _NUMBER_RE.findall(text)
        if not matches:
            return None
        return matches[-1].replace(",", "")
    if method == "first_number":
        match = _NUMBER_RE.search(text)
        if not match:
            return None
        return match.group(0).replace(",", "")
    if method == "letter":
        match = _LETTER_RE.search(text)
        if not match:
            return None
        return match.group(1)
    return text.strip()


def _to_number(value):
    try:
        return float(str(value).strip().replace(",", "").rstrip("."))
    except (TypeError, ValueError):
        return None


def _clean_number(value: float):
    """Return an int when the value is integral, so scores print as `8`."""
    if value is None:
        return None
    if float(value).is_integer():
        return int(value)
    return value


def values_match(extracted, expected) -> bool:
    if extracted is None:
        return False
    a = str(extracted).strip()
    b = ("" if expected is None else str(expected)).strip()
    if a == b:
        return True
    na, nb = _to_number(a), _to_number(b)
    if na is not None and nb is not None:
        return na == nb or math.isclose(na, nb, rel_tol=1e-9, abs_tol=1e-9)
    return False


def evaluate(config: Config, text: str, row: dict):
    """Return (passed, extracted_answer). passed is None when no evaluation.

    Only covers the local evaluation types; `llm_judge` and `script` are
    handled by the runner because they need I/O.
    """
    ev = config.evaluation
    if ev is None:
        return None, None
    extracted = extract_answer(text, ev["extract"])
    etype = ev["type"]
    if etype == "exact_match":
        passed = values_match(extracted, row.get(ev["answer_field"]))
    elif etype == "contains":
        expected = row.get(ev["answer_field"])
        expected = "" if expected is None else str(expected)
        passed = expected in (text or "")
    elif etype == "regex":
        passed = re.search(ev["pattern"], text or "") is not None
    else:
        return None, None
    return bool(passed), extracted


# --------------------------------------------------------------------------
# HTTP transport
# --------------------------------------------------------------------------

class HttpError(Exception):
    def __init__(self, message, status=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class Transport:
    """POST JSON and return a decoded object. aiohttp when available."""

    def __init__(self, concurrency: int, timeout: float = 1200.0):
        self.concurrency = concurrency
        self.timeout = timeout
        self._session = None
        self._executor = None
        self._aiohttp = None

    async def __aenter__(self):
        try:
            import aiohttp  # type: ignore
            self._aiohttp = aiohttp
            connector = aiohttp.TCPConnector(limit=max(self.concurrency, 1))
            timeout = aiohttp.ClientTimeout(total=self.timeout, sock_connect=30)
            self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        except ImportError:
            from concurrent.futures import ThreadPoolExecutor
            self._executor = ThreadPoolExecutor(max_workers=max(self.concurrency, 1) + 4)
        return self

    async def __aexit__(self, *exc):
        if self._session is not None:
            await self._session.close()
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        return False

    async def post_json(self, url: str, payload: dict) -> dict:
        if self._session is not None:
            return await self._post_aiohttp(url, payload)
        return await asyncio.get_event_loop().run_in_executor(
            self._executor, self._post_urllib, url, payload)

    async def _post_aiohttp(self, url: str, payload: dict) -> dict:
        aiohttp = self._aiohttp
        try:
            async with self._session.post(
                    url, json=payload,
                    headers={"Content-Type": "application/json"}) as resp:
                body = await resp.read()
                status = resp.status
        except asyncio.TimeoutError:
            raise HttpError("request timed out", retryable=True)
        except aiohttp.ClientError as exc:
            raise HttpError("connection error: %s" % exc, retryable=True)
        return _handle_response(status, body)

    def _post_urllib(self, url: str, payload: dict) -> dict:
        import urllib.error
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return _handle_response(resp.status, resp.read())
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass
            return _handle_response(exc.code, body)
        except Exception as exc:
            raise HttpError("connection error: %s" % exc, retryable=True)


def _handle_response(status: int, body: bytes) -> dict:
    if 500 <= status < 600:
        raise HttpError("server error: HTTP %d" % status, status=status, retryable=True)
    if status < 200 or status >= 300:
        raise HttpError("HTTP %d: %s" % (status, _snippet(body)), status=status, retryable=False)
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HttpError("invalid JSON response: %s" % exc, status=status, retryable=False)


def _snippet(body: bytes, limit: int = 200) -> str:
    try:
        text = body.decode("utf-8", "replace")
    except Exception:
        return ""
    text = text.strip().replace("\n", " ")
    return text[:limit]


class RateLimiter:
    """Token bucket pacing requests at `rpm` per minute.

    The bucket capacity is the number of requests we are willing to have in
    flight at once. By Little's law, sustaining `rate` requests per second
    against a server that takes L seconds per request needs rate * L requests
    in flight, so the capacity grows as request latency is observed. Growing
    it credits the difference as tokens, which fills the pipeline once and
    then leaves the steady-state issue rate at `rpm`.
    """

    def __init__(self, rpm: float, max_burst: int):
        self.rate = max(rpm, 1e-9) / 60.0
        self.max_burst = max(1, max_burst)
        # Start out assuming roughly one second of latency.
        self.capacity = max(1.0, min(float(self.max_burst), self.rate + 1.0))
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()

    def observe_latency(self, seconds: float):
        target = min(float(self.max_burst), self.rate * seconds * 1.25 + 1.0)
        if target > self.capacity:
            self.tokens = min(target, self.tokens + (target - self.capacity))
            self.capacity = target

    async def acquire(self):
        while True:
            async with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.rate
            await asyncio.sleep(min(wait, 5.0))


class Stats:
    """Call/token counters. A task's Stats forwards into the run-wide parent."""

    def __init__(self, parent=None):
        self.parent = parent
        self.api_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.first_start = None
        self.last_end = None

    def add_call(self):
        self.api_calls += 1
        if self.parent is not None:
            self.parent.add_call()

    def add_tokens(self, prompt_tokens, completion_tokens):
        self.prompt_tokens += prompt_tokens or 0
        self.completion_tokens += completion_tokens or 0
        if self.parent is not None:
            self.parent.add_tokens(prompt_tokens, completion_tokens)

    def mark_start(self, t: float):
        if self.first_start is None or t < self.first_start:
            self.first_start = t
        if self.parent is not None:
            self.parent.mark_start(t)

    def mark_end(self, t: float):
        if self.last_end is None or t > self.last_end:
            self.last_end = t
        if self.parent is not None:
            self.parent.mark_end(t)

    @property
    def elapsed(self) -> float:
        if self.first_start is None or self.last_end is None:
            return 0.0
        return max(0.0, self.last_end - self.first_start)


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def _kill_process_tree(proc) -> None:
    """SIGKILL a script's whole process group, falling back to the shell."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        return
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


class Runner:
    def __init__(self, config: Config, transport: Transport, limiter: RateLimiter,
                 semaphore: asyncio.Semaphore, stats: Stats, script_semaphore=None):
        self.config = config
        self.transport = transport
        self.limiter = limiter
        self.semaphore = semaphore
        self.stats = stats
        self.script_semaphore = script_semaphore
        self.url = config.api_url + (
            "/v1/completions" if config.api_type == "completions" else "/v1/chat/completions")
        self.tools_by_name = {tool["name"]: tool for tool in config.tools}

    def build_messages(self, row: dict, setup=None):
        """System message, then the ICL examples as alternating user/assistant
        turns, then the real user message."""
        messages = []
        if self.config.system_prompt is not None:
            messages.append({"role": "system",
                             "content": render_template(self.config.system_prompt, row)})
        if setup is not None:
            for example in setup["examples"]:
                messages.append({"role": "user",
                                 "content": render_example(self.config.user_prompt,
                                                           example["input"])})
                messages.append({"role": "assistant", "content": example["output"]})
        messages.append({"role": "user",
                         "content": render_template(self.config.user_prompt, row)})
        return messages

    def choose_setup(self, index: int):
        """Pick the ICL setup for attempt `index` (0-based)."""
        setups = self.config.icl_setups
        if not setups:
            return None
        strategy = self.config.icl_strategy
        if strategy == "random":
            return random.choice(setups)
        if strategy == "round_robin":
            return setups[index % len(setups)]
        return setups[0]

    def build_payload(self, messages, model=None, temperature=None, with_tools=False):
        """A chat payload, or a `/v1/completions` payload carrying a rendered
        prompt string when the task runs in completions mode."""
        cfg = self.config
        temp = cfg.temperature if temperature is None else temperature
        tools = cfg.tools if (with_tools and cfg.tools) else None
        if cfg.api_type == "completions":
            if tools:
                messages = with_tool_instructions(messages, tools)
            return {
                "model": model or cfg.model,
                "prompt": render_chat_template(cfg.chat_template, messages),
                "temperature": temp,
                "max_tokens": cfg.max_tokens,
            }
        payload = {
            "model": model or cfg.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": cfg.max_tokens,
        }
        if tools:
            payload["tools"] = cfg.tool_specs()
        return payload

    async def call_once(self, payload: dict) -> dict:
        """One logical API call, retrying 5xx up to MAX_HTTP_RETRIES times.

        Returns a dict with 'ok', 'content', 'meta'.
        """
        model = payload.get("model")
        last_error = None
        attempt = 0
        latency_ms = 0
        while attempt <= MAX_HTTP_RETRIES:
            if attempt:
                await asyncio.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))
            await self.limiter.acquire()
            async with self.semaphore:
                start = time.monotonic()
                self.stats.mark_start(start)
                self.stats.add_call()
                try:
                    data = await self.transport.post_json(self.url, payload)
                    error = None
                except HttpError as exc:
                    data, error = None, exc
                except Exception as exc:  # unexpected client-side failure
                    data, error = None, HttpError(str(exc), retryable=False)
                end = time.monotonic()
                self.stats.mark_end(end)
            latency_ms = int(round((end - start) * 1000))
            self.limiter.observe_latency(end - start)
            attempt += 1

            if error is None:
                try:
                    content, meta, message = self._parse_completion(data, latency_ms, model)
                except HttpError as exc:
                    last_error = exc
                    break
                self.stats.add_tokens(meta["prompt_tokens"], meta["completion_tokens"])
                return {"ok": True, "content": content, "meta": meta, "message": message}

            last_error = error
            if not error.retryable:
                break

        return {
            "ok": False,
            "content": None,
            "message": None,
            "meta": {
                "model": model,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "latency_ms": latency_ms,
                "finish_reason": None,
                "error": str(last_error) if last_error else "request failed",
            },
        }

    def _parse_completion(self, data, latency_ms: int, model=None):
        if not isinstance(data, dict):
            raise HttpError("unexpected response shape")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise HttpError("response contained no choices")
        choice = choices[0] or {}
        message = choice.get("message")
        if not isinstance(message, dict):
            message = {}
        content = message.get("content")
        if content is None:
            content = choice.get("text")
        if content is None:
            content = ""
        usage = data.get("usage") or {}
        meta = {
            "model": model or self.config.model,
            "prompt_tokens": _as_int(usage.get("prompt_tokens")),
            "completion_tokens": _as_int(usage.get("completion_tokens")),
            "total_tokens": _as_int(usage.get("total_tokens")),
            "latency_ms": latency_ms,
            "finish_reason": choice.get("finish_reason"),
        }
        return content, meta, message

    # -- tools ------------------------------------------------------------
    def extract_tool_calls(self, result: dict):
        """Tool calls from one API response, native or text-encoded."""
        if self.config.api_type == "completions":
            return parse_text_tool_calls(result.get("content"))
        return parse_tool_calls(result.get("message") or {})

    def assistant_tool_message(self, result: dict, calls):
        """The assistant turn to append before the tool results."""
        if self.config.api_type == "completions":
            return {"role": "assistant", "content": result.get("content") or ""}
        message = result.get("message") or {}
        return {
            "role": "assistant",
            "content": message.get("content"),
            "tool_calls": [
                {"id": call["id"], "type": call["type"],
                 "function": {"name": call["function"]["name"],
                              "arguments": call["function"]["arguments"]
                              if isinstance(call["function"]["arguments"], str)
                              else json.dumps(call["function"]["arguments"] or {},
                                              ensure_ascii=False)}}
                for call in calls
            ],
        }

    def tool_result_message(self, call, name: str, output: str):
        if self.config.api_type == "completions":
            return {"role": "tool", "name": name, "content": output}
        return {"role": "tool", "tool_call_id": call["id"], "name": name, "content": output}

    async def execute_tool(self, name: str, args: dict) -> str:
        """Run one tool call and return its result as a string."""
        tool = self.tools_by_name.get(name)
        if tool is None:
            return "ERROR: unknown tool %r" % name
        handler = tool["handler"]
        htype = handler["type"]
        if htype == "echo":
            return json.dumps(args, ensure_ascii=False)
        if htype == "static_map":
            key_field = handler["key_field"]
            if key_field is not None and key_field in args:
                key = args[key_field]
                key = key if isinstance(key, str) else _render_value(key)
                if key in handler["mapping"]:
                    return _render_value(handler["mapping"][key])
            return _render_value(handler["default"])
        if htype == "script":
            if self.script_semaphore is not None:
                async with self.script_semaphore:
                    return await self._run_tool_script(handler, args)
            return await self._run_tool_script(handler, args)
        return "ERROR: unsupported handler type %r" % htype

    @staticmethod
    async def _run_tool_script(handler, args) -> str:
        """`command` plus the `arg_field` value as one argv entry."""
        value = args.get(handler["arg_field"], "")
        argument = value if isinstance(value, str) else _render_value(value)
        try:
            argv = shlex.split(handler["command"]) + [argument]
        except ValueError as exc:
            return "ERROR: %s" % exc
        if not argv:
            return "ERROR: empty command"
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True)
        except Exception as exc:
            return "ERROR: %s" % exc
        communicate = asyncio.ensure_future(proc.communicate())
        try:
            stdout, stderr = await asyncio.wait_for(asyncio.shield(communicate),
                                                    timeout=TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            _kill_process_tree(proc)
            try:
                await asyncio.wait_for(communicate, timeout=SCRIPT_KILL_GRACE)
            except Exception:
                communicate.cancel()
            return "ERROR: command timed out after %g seconds" % TOOL_TIMEOUT
        except Exception as exc:
            _kill_process_tree(proc)
            communicate.cancel()
            return "ERROR: %s" % exc
        if proc.returncode != 0:
            detail = (stderr or b"").decode("utf-8", "replace").strip()
            if not detail:
                detail = "command exited with status %s" % proc.returncode
            return "ERROR: %s" % detail
        return (stdout or b"").decode("utf-8", "replace").strip()

    # -- agentic loop -----------------------------------------------------
    async def run_agentic_loop(self, row: dict, setup=None) -> dict:
        """Call the API, run any requested tools, repeat until the model
        answers in plain text or `max_iterations` API requests are spent."""
        cfg = self.config
        messages = self.build_messages(row, setup)
        tool_records = []
        details = []
        iterations = 0
        content = None
        finish_reason = None
        error = None
        start = time.monotonic()

        while iterations < cfg.max_iterations:
            payload = self.build_payload(messages, with_tools=cfg.tools_enabled)
            result = await self.call_once(payload)
            iterations += 1
            meta = result["meta"]
            detail = {
                "prompt_tokens": meta["prompt_tokens"],
                "completion_tokens": meta["completion_tokens"],
                "total_tokens": meta["total_tokens"],
                "latency_ms": meta["latency_ms"],
                "finish_reason": meta["finish_reason"],
            }
            if meta.get("error") is not None:
                detail["error"] = meta["error"]
            details.append(detail)

            if not result["ok"]:
                error = meta.get("error") or "request failed"
                break

            calls = self.extract_tool_calls(result)
            if not calls:
                content = result["content"]
                finish_reason = meta.get("finish_reason") or "stop"
                break

            messages.append(self.assistant_tool_message(result, calls))
            for call in calls:
                name = call["function"]["name"]
                args = parse_tool_arguments(call["function"]["arguments"])
                output = await self.execute_tool(name, args)
                tool_records.append({
                    "iteration": iterations,
                    "tool": name,
                    "args": args,
                    "result": output,
                })
                messages.append(self.tool_result_message(call, name, output))
        else:
            finish_reason = "max_iterations"

        latency_ms = int(round((time.monotonic() - start) * 1000))
        agg = {
            "total_prompt_tokens": sum(d["prompt_tokens"] or 0 for d in details),
            "total_completion_tokens": sum(d["completion_tokens"] or 0 for d in details),
            "total_tokens": sum(d["total_tokens"] or 0 for d in details),
            "latency_ms": latency_ms,
            "finish_reason": finish_reason,
            "iterations_detail": details,
        }
        if error is not None:
            agg["error"] = error
        return {
            "content": content,
            "iterations": iterations,
            "tool_calls": tool_records,
            "meta": agg,
            "error": error,
        }

    # -- evaluation -------------------------------------------------------
    async def evaluate_response(self, content: str, row: dict):
        """Return (passed, extracted, judge_score, judge_meta)."""
        ev = self.config.evaluation
        if ev is None:
            return None, None, None, None
        if ev["type"] == "llm_judge":
            return await self._evaluate_judge(content, row)
        if ev["type"] == "script":
            passed = await self._evaluate_script(content, row)
            return bool(passed), None, None, None
        passed, extracted = evaluate(self.config, content, row)
        return passed, extracted, None, None

    async def _evaluate_judge(self, content: str, row: dict):
        ev = self.config.evaluation
        context = dict(row)
        context[RESPONSE_KEY] = content if content is not None else ""
        messages = []
        if ev["judge_system"] is not None:
            messages.append({"role": "system",
                             "content": render_template(ev["judge_system"], context)})
        messages.append({"role": "user",
                         "content": render_template(ev["judge_user"], context)})
        payload = self.build_payload(
            messages, model=ev["judge_model"] or self.config.model, temperature=0.0)
        result = await self.call_once(payload)
        judge_meta = result["meta"]
        if not result["ok"]:
            return False, None, None, judge_meta
        extracted = extract_answer(result["content"], ev["extract"])
        score = _to_number(extracted)
        if score is None:
            return False, extracted, None, judge_meta
        return bool(score >= ev["threshold"]), extracted, _clean_number(score), judge_meta

    async def _evaluate_script(self, content: str, row: dict) -> bool:
        ev = self.config.evaluation
        command = render_command(ev["command_template"], row,
                                 content if content is not None else "")
        if self.script_semaphore is not None:
            async with self.script_semaphore:
                return await self._run_command(command, ev["success_exit_code"])
        return await self._run_command(command, ev["success_exit_code"])

    @staticmethod
    async def _run_command(command: str, success_exit_code: int) -> bool:
        try:
            # Its own session, so a timeout can kill the shell *and* whatever
            # it spawned - otherwise a surviving grandchild keeps the captured
            # pipes open and communicate() blocks past the deadline.
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True)
        except Exception:
            return False
        # stdout/stderr are drained so a chatty command cannot fill its pipe
        # and deadlock, and so neither stream reaches the JSONL output.
        communicate = asyncio.ensure_future(proc.communicate())
        try:
            # Shielded: on timeout the reader keeps running until the killed
            # process closes its pipes, rather than being left half-cancelled.
            await asyncio.wait_for(asyncio.shield(communicate), timeout=SCRIPT_TIMEOUT)
        except asyncio.TimeoutError:
            _kill_process_tree(proc)
            try:
                await asyncio.wait_for(communicate, timeout=SCRIPT_KILL_GRACE)
            except Exception:
                communicate.cancel()
            return False
        except Exception:
            _kill_process_tree(proc)
            communicate.cancel()
            return False
        return proc.returncode == success_exit_code

    # -- per-row driver ---------------------------------------------------
    async def process_row(self, row: dict) -> dict:
        if self.config.list_format:
            return await self.process_row_multi(row)
        if self.config.scheme == "agentic":
            return await self.process_row_agentic(row)
        return await self.process_row_single(row)

    def _setup_sequence(self):
        """Yield the ICL setup to use for each attempt, in order.

        Greedy with ICL and num_solutions > 1 walks the declared setups once
        each, ignoring `icl.strategy`; every other combination follows the
        strategy. The caller stops early once it has what it needs.
        """
        cfg = self.config
        if cfg.scheme == "greedy":
            if cfg.icl_configured and cfg.num_solutions > 1:
                for setup in cfg.icl_setups:
                    yield setup
                return
            yield self.choose_setup(0)
            return
        if cfg.scheme in ("sample", "agentic"):
            limit = cfg.num_solutions
        else:  # rejection
            limit = cfg.max_attempts
        for index in range(limit):
            yield self.choose_setup(index)

    async def process_row_multi(self, row: dict) -> dict:
        """Collect up to `num_solutions` outputs for one row (Part 3 format)."""
        cfg = self.config
        outputs = []
        metas = []
        attempts = 0
        passed_count = 0

        for setup in self._setup_sequence():
            setup_name = setup["name"] if setup is not None else None
            if cfg.scheme == "agentic":
                loop = await self.run_agentic_loop(row, setup)
                content = loop["content"]
                meta = loop["meta"]
            else:
                result = await self.call_once(self.build_payload(
                    self.build_messages(row, setup)))
                meta = result["meta"]
                content = result["content"] if result["ok"] else None
            attempts += 1

            if content is not None:
                passed, _extracted, _score, judge_meta = await self.evaluate_response(content, row)
                if judge_meta is not None:
                    meta["judge_meta"] = judge_meta
            else:
                passed = None if cfg.evaluation is None else False

            meta["icl_setup"] = setup_name
            meta["evaluation_passed"] = passed if cfg.evaluation is not None else None
            metas.append(meta)

            if content is not None and (cfg.scheme != "rejection" or passed):
                outputs.append({cfg.output_field: content, "icl_setup": setup_name})
            if passed:
                passed_count += 1

            if cfg.scheme == "rejection":
                if passed_count >= cfg.num_solutions:
                    break
            elif len(outputs) >= cfg.num_solutions:
                break

        collected = len(outputs) if cfg.evaluation is None else passed_count
        return {
            "input": row,
            "output": outputs,
            "result": {
                "passed": collected,
                "failed": attempts - collected,
                "attempts": attempts,
            },
            "meta": metas,
        }

    async def process_row_agentic(self, row: dict) -> dict:
        """One agentic loop for a row that keeps the Part 1 row shape."""
        cfg = self.config
        loop = await self.run_agentic_loop(row)
        content = loop["content"]
        meta = loop["meta"]
        judge_score = None
        if content is None:
            passed = None if cfg.evaluation is None else False
            extracted = None
        else:
            passed, extracted, judge_score, judge_meta = await self.evaluate_response(content, row)
            if judge_meta is not None:
                meta["judge_meta"] = judge_meta

        result_obj = {
            "passed": passed,
            "extracted_answer": extracted,
            "attempts": 1,
            "iterations": loop["iterations"],
            "tool_calls": loop["tool_calls"],
        }
        if cfg.eval_type == "llm_judge":
            result_obj["judge_score"] = judge_score

        return {
            "input": row,
            "output": None if content is None else {cfg.output_field: content},
            "result": result_obj,
            "meta": meta,
        }

    async def process_row_single(self, row: dict) -> dict:
        cfg = self.config
        payload = self.build_payload(self.build_messages(row))
        metas = []
        attempts = 0
        content = None
        passed = None
        extracted = None
        judge_score = None
        max_attempts = cfg.n if cfg.scheme == "rejection" else 1

        while attempts < max_attempts:
            result = await self.call_once(payload)
            attempts += 1
            meta = result["meta"]
            metas.append(meta)
            if not result["ok"]:
                content = None
                passed = False if cfg.evaluation is not None else None
                extracted = None
                judge_score = None
                break
            content = result["content"]
            passed, extracted, judge_score, judge_meta = await self.evaluate_response(content, row)
            if judge_meta is not None:
                meta["judge_meta"] = judge_meta
            if cfg.scheme != "rejection":
                break
            if passed:
                break
            if attempts < max_attempts:
                content = None
                extracted = None
                judge_score = None

        api_failed = bool(metas) and metas[-1].get("error") is not None
        if cfg.scheme == "rejection" and (api_failed or not passed):
            content = None
            extracted = None
            judge_score = None
            passed = False

        if content is None:
            output = None
            extracted = None
            judge_score = None
            if api_failed:
                passed = None if cfg.evaluation is None else False
        else:
            output = {cfg.output_field: content}

        result_obj = {
            "passed": passed,
            "extracted_answer": extracted,
            "attempts": attempts,
        }
        if cfg.eval_type == "llm_judge":
            result_obj["judge_score"] = judge_score

        return {
            "input": row,
            "output": output,
            "result": result_obj,
            "meta": metas[0] if len(metas) == 1 else metas,
        }


def _as_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Input / output
# --------------------------------------------------------------------------

def read_config(path: str) -> dict:
    if not os.path.exists(path):
        raise ConfigError("config file not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise ConfigError("cannot read config file %s: %s" % (path, exc))
    try:
        data = load_yaml(text)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError("cannot parse YAML config %s: %s" % (path, exc))
    return data


def read_rows(path: str):
    if not os.path.exists(path):
        raise ConfigError("input file not found: %s" % path)
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    raise ConfigError(
                        "invalid JSON on line %d of %s: %s" % (lineno, path, exc))
                if not isinstance(obj, dict):
                    raise ConfigError(
                        "line %d of %s is not a JSON object" % (lineno, path))
                rows.append(obj)
    except OSError as exc:
        raise ConfigError("cannot read input file %s: %s" % (path, exc))
    return rows


def required_row_fields(config: Config):
    """Template fields every row must carry, plus the evaluation answer field."""
    fields = list(template_fields(config.system_prompt or ""))
    fields += list(template_fields(config.user_prompt))
    answer_field = None
    ev = config.evaluation
    if ev is not None:
        if ev["type"] in ("exact_match", "contains"):
            answer_field = ev.get("answer_field")
        if ev["type"] == "llm_judge":
            fields += template_fields(ev["judge_system"] or "")
            fields += template_fields(ev["judge_user"] or "")
        if ev["type"] == "script":
            fields += template_fields(ev["command_template"] or "")
    fields = [f for f in fields if f != RESPONSE_KEY]
    return fields, answer_field


def validate_rows(config: Config, rows, label=None):
    fields, answer_field = required_row_fields(config)
    where = "" if not label else " of task %r" % label
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise ConfigError(
                    "row %d%s is missing field %r required by the prompt template"
                    % (index, where, field))
        if answer_field is not None and answer_field not in row:
            raise ConfigError(
                "row %d%s is missing field %r required by the evaluation"
                % (index, where, answer_field))


def write_results(path: str, results):
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise ConfigError("cannot create output directory %s: %s" % (directory, exc))
    try:
        with open(path, "w", encoding="utf-8") as fh:
            for item in results:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ConfigError("cannot write output file %s: %s" % (path, exc))


def _tally(results):
    """Count rows, not solutions: a row passes when it yielded a passing output."""
    passed = failed = 0
    for item in results:
        output = item["output"]
        row_passed = item["result"]["passed"]
        if isinstance(output, list):
            if row_passed > 0:
                passed += 1
            else:
                failed += 1
        elif output is None:
            failed += 1
        elif row_passed is True or row_passed is None:
            passed += 1
        else:
            failed += 1
    return passed, failed


def _row_solutions(item) -> int:
    output = item["output"]
    if isinstance(output, list):
        return len(output)
    return 0 if output is None else 1


def _solution_counts(results):
    total_solutions = sum(_row_solutions(item) for item in results)
    average = (total_solutions / float(len(results))) if results else 0.0
    return total_solutions, round(average, 2)


def summarize(results, stats: Stats, per_task=None) -> dict:
    passed, failed = _tally(results)
    elapsed = stats.elapsed
    throughput = (stats.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0
    summary = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
    }
    # Solution counts only appear once a run actually produces solution lists,
    # so single-solution runs without ICL keep the Part 1 summary shape.
    if any(isinstance(item["output"], list) for item in results):
        total_solutions, average = _solution_counts(results)
        summary["total_solutions"] = total_solutions
        summary["avg_solutions_per_input"] = average
    summary.update({
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    })
    if per_task is not None:
        summary["tasks"] = per_task
    return summary


def task_summary(results, stats: Stats) -> dict:
    passed, failed = _tally(results)
    total_solutions, average = _solution_counts(results)
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "total_solutions": total_solutions,
        "avg_solutions_per_input": average,
        "total_api_calls": stats.api_calls,
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def compute_concurrency(budget_rpm: float, row_count: int) -> int:
    """Upper bound on requests in flight; the rate limiter does the pacing."""
    target = max(int(math.ceil(budget_rpm)), 32)
    concurrency = max(1, min(target, DEFAULT_CONCURRENCY_CAP))
    return max(1, min(concurrency, max(row_count, 1)))


async def run_jobs_async(jobs):
    """Run every (name, config, rows) job concurrently through one transport.

    Tasks sharing an `api_url` share a rate limiter, so the configured `rpm`
    stays a budget for that server rather than a per-task multiplier. Row
    order is preserved within each task.
    """
    global_stats = Stats()
    task_stats = {name: Stats(parent=global_stats) for name, _, _ in jobs}
    results_by_name = {name: [] for name, _, _ in jobs}
    total_rows = sum(len(rows) for _, _, rows in jobs)
    if total_rows == 0:
        return results_by_name, global_stats, task_stats

    rpm_by_url = {}
    for _, config, _ in jobs:
        rpm_by_url[config.api_url] = max(rpm_by_url.get(config.api_url, 0.0), config.rpm)
    budget = sum(rpm_by_url.values()) or 60.0
    concurrency = compute_concurrency(budget, total_rows)

    limiters = {url: RateLimiter(rpm, max_burst=concurrency) for url, rpm in rpm_by_url.items()}
    semaphore = asyncio.Semaphore(concurrency)
    script_semaphore = asyncio.Semaphore(max(1, min(concurrency, MAX_SCRIPT_CONCURRENCY)))

    futures = {}
    async with Transport(concurrency) as transport:
        for name, config, rows in jobs:
            runner = Runner(config, transport, limiters[config.api_url], semaphore,
                            task_stats[name], script_semaphore)
            futures[name] = [asyncio.ensure_future(runner.process_row(row)) for row in rows]
        pending = [fut for group in futures.values() for fut in group]
        if pending:
            await asyncio.gather(*pending)
    for name, group in futures.items():
        results_by_name[name] = [fut.result() for fut in group]
    return results_by_name, global_stats, task_stats


async def run_async(config: Config, rows) -> tuple:
    name = config.name or "task"
    results_by_name, stats, _ = await run_jobs_async([(name, config, rows)])
    return results_by_name[name], stats


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="rejector.py",
                     description="Run prompts against an OpenAI-compatible chat API.")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="run one or more tasks over JSONL input files")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--input", action="append", default=None,
                     help="JSONL input file, or task=path for multi-task configs")
    run.add_argument("--input-dir", dest="input_dir", default=None,
                     help="directory holding <task_name>.jsonl for each task")
    run.add_argument("--output", required=True,
                     help="JSONL output file, or output directory for multi-task configs")
    run.add_argument("--task", action="append", dest="task_names", default=None,
                     help="run only this task (repeatable)")
    run.add_argument("--eval-model", dest="eval_model", default=None,
                     help="override the judge model for llm_judge tasks")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", choices=list(VALID_SCHEMES), default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    run.add_argument("--num-solutions", dest="num_solutions", type=int, default=None,
                     help="number of solutions to collect per input row")
    run.add_argument("--icl-strategy", dest="icl_strategy",
                     choices=list(VALID_ICL_STRATEGIES), default=None,
                     help="how to pick an ICL setup per attempt")
    run.add_argument("--icl-k", dest="icl_k", type=int, default=None,
                     help="use at most this many examples from the chosen ICL setup")
    run.add_argument("--api-type", dest="api_type", choices=list(VALID_API_TYPES),
                     default=None, help="chat completions or text completions endpoint")
    run.add_argument("--chat-template", dest="chat_template",
                     choices=list(VALID_CHAT_TEMPLATES), default=None,
                     help="prompt template used to render messages in completions mode")
    run.add_argument("--max-iterations", dest="max_iterations", type=int, default=None,
                     help="API requests allowed per agentic loop")
    return parser


def resolve_inputs(config_set: ConfigSet, args) -> dict:
    """Map each selected task name to the JSONL path that feeds it."""
    inputs = list(args.input or [])
    input_dir = args.input_dir

    if inputs and input_dir:
        raise ConfigError("--input and --input-dir cannot be combined; pick one mode")
    if not inputs and not input_dir:
        if config_set.multi:
            raise ConfigError("--input <task=path> or --input-dir is required")
        raise ConfigError("--input is required")

    names = config_set.names

    if input_dir:
        if not os.path.isdir(input_dir):
            raise ConfigError("input directory not found: %s" % input_dir)
        resolved = {}
        for name in names:
            if not name:
                raise ConfigError("--input-dir needs a task name; set task.name in the config")
            path = os.path.join(input_dir, "%s.jsonl" % name)
            if not os.path.exists(path):
                raise ConfigError(
                    "no input file for task %r in %s (expected %s.jsonl)"
                    % (name, input_dir, name))
            resolved[name] = path
        return resolved

    if not config_set.multi:
        if len(inputs) > 1:
            raise ConfigError("--input may only be given once for a single-task config")
        value = inputs[0]
        name = names[0]
        prefix, sep, rest = value.partition("=")
        if sep and name is not None and prefix == name:
            value = rest
        if not value:
            raise ConfigError("--input path is empty")
        return {name: value}

    resolved = {}
    for item in inputs:
        prefix, sep, path = item.partition("=")
        if not sep:
            raise ConfigError(
                "--input must be given as task=path for multi-task configs, got %r" % item)
        if prefix not in config_set.order:
            raise ConfigError(
                "--input names unknown task %r (available: %s)"
                % (prefix, ", ".join(config_set.order)))
        if prefix not in names:
            continue  # not selected by --task; ignored
        if prefix in resolved:
            raise ConfigError("--input given more than once for task %r" % prefix)
        if not path:
            raise ConfigError("--input path for task %r is empty" % prefix)
        resolved[prefix] = path
    missing = [name for name in names if name not in resolved]
    if missing:
        raise ConfigError("no --input given for task %r" % missing[0])
    return resolved


def resolve_output_dir(path: str) -> str:
    if os.path.exists(path) and not os.path.isdir(path):
        raise ConfigError("--output must be a directory for multi-task configs: %s" % path)
    if not os.path.isdir(path):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            raise ConfigError("cannot create output directory %s: %s" % (path, exc))
    return path


def command_run(args) -> int:
    overrides = {
        "api_url": args.api_url,
        "model": args.model,
        "rpm": args.rpm,
        "max_tokens": args.max_tokens,
        "scheme": args.scheme,
        "temperature": args.temperature,
        "n": args.n,
        "eval_model": args.eval_model,
        "num_solutions": args.num_solutions,
        "icl_strategy": args.icl_strategy,
        "icl_k": args.icl_k,
        "api_type": args.api_type,
        "chat_template": args.chat_template,
        "max_iterations": args.max_iterations,
    }
    selected = list(args.task_names or [])
    config_dir = os.path.dirname(os.path.abspath(args.config))
    config_set = ConfigSet(read_config(args.config), overrides, selected,
                           config_dir=config_dir)

    input_paths = resolve_inputs(config_set, args)

    jobs = []
    for name in config_set.names:
        config = config_set.configs[name]
        rows = read_rows(input_paths[name])
        validate_rows(config, rows, label=name if config_set.multi else None)
        jobs.append((name, config, rows))

    if config_set.multi:
        output_dir = resolve_output_dir(args.output)

    results_by_name, stats, task_stats = asyncio.run(run_jobs_async(jobs))

    if config_set.multi:
        combined = []
        per_task = {}
        for name, _, _ in jobs:
            results = results_by_name[name]
            write_results(os.path.join(output_dir, "%s.jsonl" % name), results)
            per_task[name] = task_summary(results, task_stats[name])
            combined.extend(results)
        summary = summarize(combined, stats, per_task=per_task)
    else:
        name = config_set.names[0]
        results = results_by_name[name]
        write_results(args.output, results)
        summary = summarize(results, stats)

    sys.stdout.write(json.dumps(summary) + "\n")
    sys.stdout.flush()
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_usage(sys.stderr)
        sys.stderr.write("error: a command is required (try 'run')\n")
        return 1
    try:
        return command_run(args)
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("error: interrupted\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
