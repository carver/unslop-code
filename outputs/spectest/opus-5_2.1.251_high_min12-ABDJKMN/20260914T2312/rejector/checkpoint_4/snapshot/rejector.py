#!/usr/bin/env python3
"""rejector.py -- run YAML-configured prompting tasks over JSONL files.

    python rejector.py run --config task.yaml --input data.jsonl \
        --output results.jsonl
    python rejector.py run --config multi.yaml --input gsm8k=math.jsonl \
        --output results/

Reads a task config (Part 1 single-task, or Part 2 `defaults` + `tasks`) and
one JSONL input file per task, sends one chat-completion request per row (per
attempt, for rejection sampling) to an OpenAI-compatible API, writes one JSONL
result per input row and prints a JSON summary on stdout.

Interpretation decisions for under-specified corners are recorded in
AMBIGUITIES.md; the code refers to them as T1, T2, ...
"""

import argparse
import itertools
import json
import os
import random
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import yaml

SCHEMES = ("greedy", "sample", "rejection", "agentic")
API_TYPES = ("chat", "completions")
CHAT_TEMPLATES = ("chatml", "llama3", "mistral", "zephyr")
TOOL_HANDLERS = ("echo", "static_map", "script")
ICL_STRATEGIES = ("fixed", "random", "round_robin")
EVAL_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")

# Total HTTP calls per logical attempt: the initial call plus retries, given up
# on after the third failure (T1).
MAX_HTTP_CALLS = 3

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_OUTPUT_FIELD = "output"          # T13
DEFAULT_EXTRACT = "full"                 # T4
DEFAULT_JUDGE_EXTRACT = "first_number"   # T31
DEFAULT_TASK_NAME = "task"               # T27
DEFAULT_ICL_STRATEGY = "fixed"           # T45
DEFAULT_MAX_ITERATIONS = 10              # T63
DEFAULT_API_TYPE = "chat"                # T71
DEFAULT_CHAT_TEMPLATE = "chatml"         # T72
DEFAULT_STATIC_MAP_DEFAULT = "NOT_FOUND"  # spec: handler `default` default
TOOL_SCRIPT_TIMEOUT = 10                 # T66
REJECTION_ATTEMPTS_PER_SOLUTION = 3      # `max_attempts` default multiplier
MAX_CONCURRENCY = 64                     # T20
REQUEST_TIMEOUT = 300
SCRIPT_TIMEOUT = 10                      # spec: "command timeout is 10 seconds"
JUDGE_TEMPERATURE = 0.0                  # T34

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")   # T10
LETTER_RE = re.compile(r"\b([A-D])\b")       # T28
RESPONSE_KEY = "__response__"


class UserError(Exception):
    """A configuration or input error: reported on stderr, exit code 1."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Task:
    """The merged, validated task definition."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    @property
    def endpoint(self):
        if self.api_type == "completions":
            return self.api_url.rstrip("/") + "/v1/completions"
        return self.api_url.rstrip("/") + "/v1/chat/completions"


class IclSetup:
    """One named in-context-learning setup: a name and its examples."""

    def __init__(self, name, examples):
        self.name = name
        self.examples = examples        # [(input_mapping, output_text), ...]


class Icl:
    """A task's ICL block: the declared setups, `k` and the strategy."""

    def __init__(self, setups, k, strategy):
        self.setups = setups
        self.k = k
        self.strategy = strategy

    def examples(self, setup):
        """The first `k` examples of a setup (all of them when `k` is unset)."""
        return setup.examples if self.k is None else setup.examples[:self.k]

    def choose(self, attempt):
        """The setup for a 0-based per-row attempt index (T46)."""
        if self.strategy == "round_robin":
            return self.setups[attempt % len(self.setups)]
        if self.strategy == "random":
            return random.choice(self.setups)
        return self.setups[0]                                       # fixed


class Tool:
    """One declared tool: its API-visible schema and its local handler."""

    def __init__(self, name, description, parameters, handler):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    @property
    def definition(self):
        """The OpenAI `tools` entry: schema only, never the handler (T64)."""
        function = {"name": self.name}
        if self.description is not None:
            function["description"] = self.description
        function["parameters"] = self.parameters
        return {"type": "function", "function": function}

    @property
    def lookup_field(self):
        """`static_map`'s first required parameter (T65)."""
        params = self.parameters if isinstance(self.parameters, dict) else {}
        required = params.get("required")
        if isinstance(required, list) and required:
            return str(required[0])
        properties = params.get("properties")
        if isinstance(properties, dict) and properties:
            return str(next(iter(properties)))
        return None

    def run(self, args):
        """Invoke the handler on the parsed arguments -> a string result."""
        handler = self.handler
        kind = handler["type"]
        if kind == "echo":
            return json.dumps(args)                                 # T67
        if kind == "static_map":
            return self._static_map(args)
        return self._script(args)

    def _static_map(self, args):
        field = self.lookup_field
        if field is None and args:
            field = next(iter(args))
        default = handler_default(self.handler)
        if field is None or field not in args:
            return default                                          # T65
        return self.handler["mapping"].get(str(args[field]), default)

    def _script(self, args):
        value = args.get(self.handler["arg_field"], "")
        command = shlex.split(self.handler["command"]) + [str(value)]
        try:
            proc = subprocess.run(command, capture_output=True,
                                  timeout=TOOL_SCRIPT_TIMEOUT)
        except subprocess.TimeoutExpired:
            return "ERROR: command timed out after %d seconds" \
                % TOOL_SCRIPT_TIMEOUT                               # T66
        except OSError as exc:
            return "ERROR: %s" % exc
        if proc.returncode != 0:
            message = proc.stderr.decode("utf-8", "replace").strip() \
                or "command exited with status %d" % proc.returncode
            return "ERROR: %s" % message
        return proc.stdout.decode("utf-8", "replace").strip()       # T68


def handler_default(handler):
    default = handler.get("default")
    return DEFAULT_STATIC_MAP_DEFAULT if default is None else str(default)


def build_tools(raw, prefix):
    """Validate the task's `tools` block -> [Tool, ...] ([] when absent)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise UserError("%s.tools must be a list of tool definitions" % prefix)
    tools = []
    for index, item in enumerate(raw):
        where = "%s.tools[%d]" % (prefix, index)
        if not isinstance(item, dict):
            raise UserError("%s must be a mapping" % where)
        name = _require_text(item.get("name"), "%s.name" % where)
        description = item.get("description")
        if description is not None and not isinstance(description, str):
            raise UserError("%s.description must be a string" % where)
        parameters = item.get("parameters")
        if parameters is None:
            parameters = {"type": "object", "properties": {}}       # T69
        if not isinstance(parameters, dict):
            raise UserError("%s.parameters must be a mapping" % where)
        handler = build_handler(item.get("handler"), "%s.handler" % where)
        tools.append(Tool(name, description, parameters, handler))
    names = [tool.name for tool in tools]
    duplicate = next((n for n in names if names.count(n) > 1), None)
    if duplicate is not None:
        raise UserError("%s.tools declares %r twice" % (prefix, duplicate))
    return tools


def build_handler(raw, where):
    if not isinstance(raw, dict):
        raise UserError("%s is required and must be a mapping" % where)
    kind = raw.get("type")
    if kind not in TOOL_HANDLERS:
        raise UserError("%s.type must be one of %s (got %r)"
                        % (where, ", ".join(TOOL_HANDLERS), kind))
    handler = {"type": kind}
    if kind == "static_map":
        mapping = raw.get("mapping")
        if mapping is None:
            mapping = {}
        if not isinstance(mapping, dict):
            raise UserError("%s.mapping must be a mapping" % where)
        handler["mapping"] = {str(k): str(v) for k, v in mapping.items()}
        handler["default"] = raw.get("default")
    elif kind == "script":
        handler["command"] = _require_text(raw.get("command"),
                                           "%s.command (required for script)"
                                           % where)
        handler["arg_field"] = _require_text(
            raw.get("arg_field"), "%s.arg_field (required for script)" % where)
    return handler


# ---------------------------------------------------------------------------
# Chat templates (completions mode)
# ---------------------------------------------------------------------------

# Per-role message fragment plus the trailing generation prompt.  Every
# built-in template is rendered by repeating its message fragment for each
# conversation turn, so multi-turn prompts repeat the role markers (T73).
CHAT_TEMPLATE_SPECS = {
    "chatml": {
        "prefix": "",
        "message": "<|im_start|>{role}\n{content}<|im_end|>\n",
        "generation": "<|im_start|>assistant\n",
    },
    "llama3": {
        "prefix": "<|begin_of_text|>",
        "message": "<|start_header_id|>{role}<|end_header_id|>\n\n"
                   "{content}<|eot_id|>",
        "generation": "<|start_header_id|>assistant<|end_header_id|>\n\n",
    },
    "zephyr": {
        "prefix": "",
        "message": "<|{role}|>\n{content}</s>\n",
        "generation": "<|assistant|>\n",
    },
}


def render_prompt(template, messages):
    """Render a message list into one prompt string for /v1/completions."""
    if template == "mistral":
        return render_mistral(messages)
    spec = CHAT_TEMPLATE_SPECS[template]
    parts = [spec["prefix"]]
    for message in messages:
        # Contents may contain braces (tool-call JSON), so substitute by hand.
        text = spec["message"].replace("{role}", message["role"])
        parts.append(text.replace("{content}", message.get("content") or ""))
    parts.append(spec["generation"])
    return "".join(parts)


def render_mistral(messages):
    """`[INST] system\n\nuser [/INST]`, with no system role of its own (T74)."""
    parts = []
    system = None
    for message in messages:
        role = message["role"]
        content = message.get("content") or ""
        if role == "system":
            system = content if system is None else system + "\n\n" + content
        elif role == "assistant":
            parts.append("%s</s>" % content)
        elif role == "tool":
            parts.append("[TOOL_RESULTS] %s [/TOOL_RESULTS]" % content)
        else:
            if system is not None:
                content = "%s\n\n%s" % (system, content)
                system = None
            parts.append("[INST] %s [/INST]" % content)
    if system is not None:                      # a system-only conversation
        parts.append("[INST] %s [/INST]" % system)
    return "".join(parts)


TOOL_PROMPT_HEADER = "You have access to the following tools:"
TOOL_PROMPT_FOOTER = """To call a tool, reply with a block of the form:
<tool_call>
{"name": "<tool name>", "arguments": {"<argument>": "<value>"}}
</tool_call>
You may emit several such blocks in one reply.  When you have the final
answer, reply with plain text and no tool call."""


def tools_prompt_block(tools):
    """Tool definitions rendered as prompt text for completions mode (T75)."""
    lines = [TOOL_PROMPT_HEADER, ""]
    lines += [json.dumps(tool.definition["function"]) for tool in tools]
    lines += ["", TOOL_PROMPT_FOOTER]
    return "\n".join(lines)


def deep_merge(base, over):
    """`over` wins; mappings present in both are merged recursively (T25)."""
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path):
    """-> (multi, {task_name: raw_task_mapping}) in config order."""
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError as exc:
        raise UserError("cannot read config file %s: %s" % (path, exc))
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise UserError("config file %s is not valid YAML: %s" % (path, exc))
    if not isinstance(data, dict):
        raise UserError("config file %s must contain a top-level 'task' or "
                        "'tasks' mapping" % path)

    if isinstance(data.get("task"), dict):                          # T26
        raw = data["task"]
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            name = DEFAULT_TASK_NAME                                # T27
        return False, {name: raw}

    tasks = data.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        raise UserError("config file %s must contain a top-level 'task' "
                        "mapping or a non-empty 'tasks' mapping" % path)
    defaults = data.get("defaults")
    if defaults is None:
        defaults = {}
    if not isinstance(defaults, dict):
        raise UserError("config 'defaults' must be a mapping")

    merged = {}
    for name, raw in tasks.items():
        name = str(name)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise UserError("tasks.%s must be a mapping" % name)
        merged[name] = deep_merge(defaults, raw)
    return True, merged


def _require_text(value, what):
    if not isinstance(value, str) or not value.strip():
        raise UserError("%s is required and must be a non-empty string" % what)
    return value


def _as_number(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UserError("%s must be a number" % what)
    return float(value)


def _as_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int):
        raise UserError("%s must be an integer" % what)
    return value


def build_example(entry, what):
    """One ICL example, from a config list or a JSONL line -> (input, output)."""
    if not isinstance(entry, dict):
        raise UserError("%s must be an object with 'input' and 'output'" % what)
    for key in ("input", "output"):
        if key not in entry:
            raise UserError("%s is missing the '%s' key" % (what, key))
    if not isinstance(entry["input"], dict):
        raise UserError("%s: 'input' must be an object" % what)
    if not isinstance(entry["output"], str):
        raise UserError("%s: 'output' must be a string" % what)
    return entry["input"], entry["output"]


def load_icl_file(path, what):
    """Read a file-backed setup; any malformed line is fatal (exit 1)."""
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise UserError("%s: cannot read ICL example file %s: %s"
                        % (what, path, exc))
    examples = []
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue                                               # T17
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise UserError("%s: %s line %d is not valid JSON: %s"
                            % (what, path, lineno, exc))
        examples.append(build_example(entry, "%s: %s line %d"
                                      % (what, path, lineno)))
    return examples


def build_icl(raw, args, prefix, config_dir):
    """Validate the `icl` block; None means 'no ICL configured' (T58, T62)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise UserError("%s.icl must be a mapping" % prefix)

    setups_raw = raw.get("setups")
    if not isinstance(setups_raw, list) or not setups_raw:
        raise UserError("%s.icl.setups must be a non-empty list of setups"
                        % prefix)

    setups = []
    for index, item in enumerate(setups_raw):
        where = "%s.icl.setups[%d]" % (prefix, index)
        if not isinstance(item, dict):
            raise UserError("%s must be a mapping" % where)
        name = _require_text(item.get("name"), "%s.name" % where)
        has_examples = item.get("examples") is not None
        has_file = item.get("file") is not None
        if has_examples == has_file:
            raise UserError("%s must have exactly one of 'examples' or 'file'"
                            % where)
        if has_file:
            path = _require_text(item.get("file"), "%s.file" % where)
            if not os.path.isabs(path):
                path = os.path.join(config_dir, path)   # relative to the config
            examples = load_icl_file(path, where)
        else:
            raw_examples = item["examples"]
            if not isinstance(raw_examples, list):
                raise UserError("%s.examples must be a list" % where)
            examples = [build_example(entry, "%s.examples[%d]" % (where, i))
                        for i, entry in enumerate(raw_examples)]   # T59
        setups.append(IclSetup(name, examples))

    k = getattr(args, "icl_k", None)
    if k is None:
        k = raw.get("k")
    if k is not None:
        k = _as_int(k, "%s.icl.k" % prefix)
        if k <= 0:                                                 # T56
            raise UserError("%s.icl.k must be a positive integer" % prefix)

    strategy = getattr(args, "icl_strategy", None)
    if strategy is None:
        strategy = raw.get("strategy") or DEFAULT_ICL_STRATEGY     # T45
    if strategy not in ICL_STRATEGIES:
        raise UserError("%s.icl.strategy must be one of %s (got %r)"
                        % (prefix, ", ".join(ICL_STRATEGIES), strategy))
    return Icl(setups, k, strategy)


def build_task(raw, args, name=None, prefix="task", config_dir="."):
    """Merge CLI overrides over the config file and validate the result."""
    generation = raw.get("generation") or {}
    if not isinstance(generation, dict):
        raise UserError("%s.generation must be a mapping" % prefix)

    api_url = args.api_url if args.api_url is not None else raw.get("api_url")
    model = args.model if args.model is not None else raw.get("model")
    rpm = args.rpm if args.rpm is not None else raw.get("rpm", DEFAULT_RPM)
    scheme = args.scheme if args.scheme is not None \
        else generation.get("scheme", "greedy")
    temperature = args.temperature if args.temperature is not None \
        else generation.get("temperature", 0.0)          # T7
    max_tokens = args.max_tokens if args.max_tokens is not None \
        else generation.get("max_tokens", DEFAULT_MAX_TOKENS)
    n = args.n if args.n is not None else generation.get("n", 1)
    num_solutions = args.num_solutions if args.num_solutions is not None \
        else raw.get("num_solutions", 1)
    max_attempts = generation.get("max_attempts")
    max_iterations = generation.get("max_iterations", DEFAULT_MAX_ITERATIONS)
    if max_iterations is None:
        max_iterations = DEFAULT_MAX_ITERATIONS                     # T63
    api_type = getattr(args, "api_type", None)
    if api_type is None:
        api_type = raw.get("api_type") or DEFAULT_API_TYPE          # T71
    chat_template = getattr(args, "chat_template", None)
    if chat_template is None:
        chat_template = raw.get("chat_template") or DEFAULT_CHAT_TEMPLATE

    _require_text(api_url, "%s.api_url" % prefix)
    _require_text(model, "%s.model" % prefix)
    rpm = _as_int(rpm, "%s.rpm" % prefix)
    if rpm <= 0:
        raise UserError("%s.rpm must be a positive integer" % prefix)
    max_tokens = _as_int(max_tokens, "%s.generation.max_tokens" % prefix)
    if max_tokens <= 0:
        raise UserError("%s.generation.max_tokens must be positive" % prefix)
    temperature = _as_number(temperature, "%s.generation.temperature" % prefix)
    n = _as_int(n, "%s.generation.n" % prefix)
    num_solutions = _as_int(num_solutions, "%s.num_solutions" % prefix)
    if num_solutions < 1:
        raise UserError("%s.num_solutions must be a positive integer" % prefix)
    if max_attempts is not None:
        max_attempts = _as_int(max_attempts,
                               "%s.generation.max_attempts" % prefix)
        if max_attempts < 1:
            raise UserError("%s.generation.max_attempts must be a positive "
                            "integer" % prefix)

    if scheme not in SCHEMES:
        raise UserError("%s.generation.scheme must be one of %s (got %r)"
                        % (prefix, ", ".join(SCHEMES), scheme))
    max_iterations = _as_int(max_iterations,
                             "%s.generation.max_iterations" % prefix)
    if max_iterations < 1:
        raise UserError("%s.generation.max_iterations must be a positive "
                        "integer" % prefix)
    if api_type not in API_TYPES:
        raise UserError("%s.api_type must be one of %s (got %r)"
                        % (prefix, ", ".join(API_TYPES), api_type))
    if chat_template not in CHAT_TEMPLATES:
        raise UserError("%s.chat_template must be one of %s (got %r)"
                        % (prefix, ", ".join(CHAT_TEMPLATES), chat_template))
    tools = build_tools(raw.get("tools"), prefix)

    prompt = raw.get("prompt")
    if not isinstance(prompt, dict):
        raise UserError("%s.prompt is required and must be a mapping" % prefix)
    system = prompt.get("system")                                   # T19
    if system is not None and not isinstance(system, str):
        raise UserError("%s.prompt.system must be a string" % prefix)
    user = _require_text(prompt.get("user"), "%s.prompt.user" % prefix)

    if scheme == "greedy":
        temperature = 0.0                                           # T8
    elif scheme != "agentic":                                       # T70
        if temperature <= 0:
            raise UserError("%s.generation.temperature must be > 0 for "
                            "scheme %r (got %r)" % (prefix, scheme, temperature))
    if scheme == "rejection" and n < 1:
        raise UserError("%s.generation.n must be >= 1 for rejection sampling"
                        % prefix)

    evaluation = build_evaluation(raw.get("evaluation"), scheme, args, prefix)

    output_field = raw.get("output_field", DEFAULT_OUTPUT_FIELD)
    if output_field is None:
        output_field = DEFAULT_OUTPUT_FIELD
    _require_text(output_field, "%s.output_field" % prefix)

    icl = build_icl(raw.get("icl"), args, prefix, config_dir)

    # Part 1 behaviour is kept only for a single-solution task with no ICL.
    legacy = num_solutions == 1 and icl is None
    if scheme != "rejection":
        attempt_limit = None                                        # T60
    elif legacy:
        attempt_limit = n                   # Part 1: `generation.n` attempts
    elif max_attempts is not None:
        attempt_limit = max_attempts                                # T50
    else:
        attempt_limit = REJECTION_ATTEMPTS_PER_SOLUTION * num_solutions

    return Task(name=name if name is not None else raw.get("name"),
                api_url=api_url, model=model, rpm=rpm,
                system_template=system, user_template=user, scheme=scheme,
                temperature=temperature, max_tokens=max_tokens, n=n,
                evaluation=evaluation, output_field=output_field,
                icl=icl, num_solutions=num_solutions,
                max_attempts=max_attempts, legacy=legacy,
                attempt_limit=attempt_limit, tools=tools,
                max_iterations=max_iterations, api_type=api_type,
                chat_template=chat_template)


def build_evaluation(raw, scheme, args=None, prefix="task"):
    """Validate the evaluation block; None means 'no evaluation configured'."""
    if raw is None:
        if scheme == "rejection":
            raise UserError("%s.evaluation is required for scheme "
                            "'rejection'" % prefix)
        return None
    if not isinstance(raw, dict):
        raise UserError("%s.evaluation must be a mapping" % prefix)

    etype = raw.get("type")
    if etype not in EVAL_TYPES:
        raise UserError("%s.evaluation.type must be one of %s (got %r)"
                        % (prefix, ", ".join(EVAL_TYPES), etype))

    default_extract = DEFAULT_JUDGE_EXTRACT if etype == "llm_judge" \
        else DEFAULT_EXTRACT
    extract = raw.get("extract") or default_extract
    if extract not in EXTRACT_METHODS:
        raise UserError("%s.evaluation.extract must be one of %s (got %r)"
                        % (prefix, ", ".join(EXTRACT_METHODS), extract))

    evaluation = {"type": etype, "extract": extract, "answer_field": None,
                  "pattern": None, "command_template": None,
                  "success_exit_code": 0, "judge_system": None,
                  "judge_user": None, "threshold": None, "judge_model": None}

    if etype in ("exact_match", "contains"):
        evaluation["answer_field"] = _require_text(
            raw.get("answer_field"),
            "%s.evaluation.answer_field (required for %s)" % (prefix, etype))
    elif etype == "regex":
        pattern = _require_text(
            raw.get("pattern"),
            "%s.evaluation.pattern (required for regex)" % prefix)
        try:
            evaluation["pattern"] = re.compile(pattern)
        except re.error as exc:
            raise UserError("%s.evaluation.pattern is not a valid regular "
                            "expression: %s" % (prefix, exc))
    elif etype == "script":
        evaluation["command_template"] = _require_text(
            raw.get("command_template"),
            "%s.evaluation.command_template (required for script)" % prefix)
        code = raw.get("success_exit_code", 0)                      # T31
        if code is None:
            code = 0
        evaluation["success_exit_code"] = _as_int(
            code, "%s.evaluation.success_exit_code" % prefix)
    else:  # llm_judge
        judge_prompt = raw.get("judge_prompt")
        if not isinstance(judge_prompt, dict):
            raise UserError("%s.evaluation.judge_prompt is required and must "
                            "be a mapping for llm_judge" % prefix)
        judge_system = judge_prompt.get("system")                   # T19
        if judge_system is not None and not isinstance(judge_system, str):
            raise UserError("%s.evaluation.judge_prompt.system must be a "
                            "string" % prefix)
        evaluation["judge_system"] = judge_system
        evaluation["judge_user"] = _require_text(
            judge_prompt.get("user"), "%s.evaluation.judge_prompt.user" % prefix)
        threshold = raw.get("threshold")                            # T31
        if threshold is None:
            raise UserError("%s.evaluation.threshold is required for "
                            "llm_judge" % prefix)
        evaluation["threshold"] = _as_number(
            threshold, "%s.evaluation.threshold" % prefix)
        judge_model = raw.get("model")
        if args is not None and getattr(args, "eval_model", None) is not None:
            judge_model = args.eval_model                           # --eval-model
        if judge_model is not None:
            judge_model = _require_text(judge_model,
                                        "%s.evaluation.model" % prefix)
        evaluation["judge_model"] = judge_model

    return evaluation


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def load_rows(path):
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise UserError("cannot read input file %s: %s" % (path, exc))
    rows = []
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue                                               # T17
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise UserError("input file %s line %d is not valid JSON: %s"
                            % (path, lineno, exc))
        if not isinstance(row, dict):
            raise UserError("input file %s line %d is not a JSON object"
                            % (path, lineno))
        rows.append(row)
    return rows


def template_fields(template):
    return [] if template is None else PLACEHOLDER_RE.findall(template)


def required_row_fields(task):
    """Every row field the task's templates and evaluation need (T11, T30)."""
    fields = template_fields(task.system_template) + \
        template_fields(task.user_template)
    evaluation = task.evaluation
    if evaluation:
        fields += template_fields(evaluation["command_template"])
        fields += template_fields(evaluation["judge_system"])
        fields += template_fields(evaluation["judge_user"])
        if evaluation["answer_field"] is not None:                 # T12
            fields.append(evaluation["answer_field"])
    return [f for f in fields if f != RESPONSE_KEY]


def validate_rows(rows, task):
    """Pre-flight every row so a bad file fails before any request (T11)."""
    fields = required_row_fields(task)
    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise UserError("row %d: missing field '%s' required by task "
                                "%r" % (index, field, task.name))


def render(template, row):
    if template is None:
        return None
    return PLACEHOLDER_RE.sub(lambda m: str(row[m.group(1)]), template)


def render_with(template, mapping):
    """Render leaving unknown placeholders untouched (one pass, no rescan)."""
    if template is None:
        return None

    def sub(match):
        key = match.group(1)
        return str(mapping[key]) if key in mapping else match.group(0)

    return PLACEHOLDER_RE.sub(sub, template)


def build_messages(task, row, setup=None):
    """System, then the setup's examples as alternating turns, then the row."""
    messages = []
    system = None
    if task.system_template is not None:                            # T57
        system = render(task.system_template, row)
    if task.scheme == "agentic" and task.api_type == "completions" \
            and task.tools:
        # No native `tools` field in completions mode: describe them in the
        # system prompt instead (T75).
        block = tools_prompt_block(task.tools)
        system = block if system is None else system + "\n\n" + block
    if system is not None:
        messages.append({"role": "system", "content": system})
    if setup is not None:
        for example_input, example_output in task.icl.examples(setup):
            messages.append({"role": "user",
                             "content": render_with(task.user_template,
                                                    example_input)})  # T55
            messages.append({"role": "assistant", "content": example_output})
    messages.append({"role": "user", "content": render(task.user_template, row)})
    return messages


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def extract_answer(text, method):
    """Reduce a response to the value the evaluation compares (None if absent)."""
    if method == "full":
        return text
    if method == "last_number":
        matches = NUMBER_RE.findall(text)
        return matches[-1] if matches else None                    # T18
    if method == "first_number":
        match = NUMBER_RE.search(text)
        return match.group(0) if match else None                   # T29
    if method == "letter":
        match = LETTER_RE.search(text)
        return match.group(1) if match else None                   # T28
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return None
    raise UserError("unknown extract method %r" % method)


def parse_number(text):
    """'8' -> 8, '7.5' -> 7.5, anything else -> None."""
    if text is None:
        return None
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return None


def render_command(command_template, row, response):
    """Row fields and `__response__`, then `__response__` once more (T32)."""
    mapping = dict(row)
    mapping[RESPONSE_KEY] = response
    rendered = render_with(command_template, mapping)
    # A row field such as {test_code} may itself expand to text containing
    # {__response__}: substitute it before executing the command.
    return rendered.replace("{%s}" % RESPONSE_KEY, response)


def run_script(evaluation, row, response):
    command = render_command(evaluation["command_template"], row, response)
    try:
        proc = subprocess.run(command, shell=True, capture_output=True,
                              timeout=SCRIPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False                    # timeout is a failed evaluation
    except OSError:
        return False
    # stdout/stderr are captured (and drained) but never reported (T33).
    return proc.returncode == evaluation["success_exit_code"]


def build_judge_messages(evaluation, row, response):
    mapping = dict(row)
    mapping[RESPONSE_KEY] = response
    messages = []
    if evaluation["judge_system"] is not None:
        messages.append({"role": "system",
                         "content": render_with(evaluation["judge_system"],
                                                mapping)})
    messages.append({"role": "user",
                     "content": render_with(evaluation["judge_user"], mapping)})
    return messages


def run_judge(task, row, response, stats):
    """-> (passed, extracted, judge_score, judge_meta)."""
    evaluation = task.evaluation
    messages = build_judge_messages(evaluation, row, response)
    model = evaluation["judge_model"] or task.model
    attempt = call_api(task, messages, stats, model=model,
                       temperature=JUDGE_TEMPERATURE)
    if not attempt.ok:
        return False, None, None, attempt.meta                     # T35
    extracted = extract_answer(attempt.content, evaluation["extract"])
    score = parse_number(extracted)
    if score is None:
        return False, extracted, None, attempt.meta
    return score >= evaluation["threshold"], extracted, score, attempt.meta


def evaluate(text, row, task, stats=None):
    """-> (passed, extracted, judge_score, judge_meta).

    passed is None when no evaluation is configured.
    """
    evaluation = task.evaluation
    if evaluation is None:
        return None, None, None, None
    etype = evaluation["type"]
    if etype == "script":
        return run_script(evaluation, row, text), None, None, None  # T33
    if etype == "llm_judge":
        return run_judge(task, row, text, stats)

    extracted = extract_answer(text, evaluation["extract"])        # T5
    if extracted is None:
        return False, None, None, None
    if etype == "exact_match":
        expected = str(row[evaluation["answer_field"]])
        return extracted.strip() == expected.strip(), extracted, None, None
    if etype == "contains":
        expected = str(row[evaluation["answer_field"]])
        return expected in extracted, extracted, None, None
    passed = evaluation["pattern"].search(extracted) is not None   # T6
    return passed, extracted, None, None


# ---------------------------------------------------------------------------
# API access
# ---------------------------------------------------------------------------

class Stats:
    """Thread-safe run-wide counters."""

    def __init__(self):
        self._lock = threading.Lock()
        self.api_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.by_task = {}
        self.first_start = None
        self.last_end = None

    def start_call(self, when):
        with self._lock:
            if self.first_start is None or when < self.first_start:
                self.first_start = when

    def end_call(self, when, prompt_tokens=0, completion_tokens=0,
                 task_name=None):
        with self._lock:
            self.api_calls += 1
            if task_name is not None:
                self.by_task[task_name] = self.by_task.get(task_name, 0) + 1
            self.prompt_tokens += prompt_tokens                    # T22
            self.completion_tokens += completion_tokens
            if self.last_end is None or when > self.last_end:
                self.last_end = when

    def task_calls(self, name):
        with self._lock:
            return self.by_task.get(name, 0)

    @property
    def elapsed(self):
        if self.first_start is None or self.last_end is None:
            return 0.0
        return max(0.0, self.last_end - self.first_start)


class Attempt:
    """The outcome of one logical generation attempt."""

    def __init__(self, ok, content, meta, message=None):
        self.ok = ok
        self.content = content
        self.meta = meta
        # The raw assistant message of a chat response (None in completions
        # mode): the agentic loop reads `tool_calls` from it.
        self.message = message


def _meta(model, latency_ms, usage=None, finish_reason=None):
    if usage is None:                                              # T3
        return {"model": model, "prompt_tokens": None,
                "completion_tokens": None, "total_tokens": None,
                "latency_ms": latency_ms, "finish_reason": None}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total = usage.get("total_tokens")
    total = int(total) if total is not None else prompt_tokens + completion_tokens
    return {"model": model, "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens, "total_tokens": total,
            "latency_ms": latency_ms, "finish_reason": finish_reason}


def request_body(task, messages, model, temperature, tools=None):
    """The JSON body for one request, in chat or completions shape."""
    if task.api_type == "completions":
        return {"model": model,
                "prompt": render_prompt(task.chat_template, messages),
                "temperature": temperature,
                "max_tokens": task.max_tokens}
    body = {"model": model, "messages": messages, "temperature": temperature,
            "max_tokens": task.max_tokens}
    if tools:
        body["tools"] = [tool.definition for tool in tools]
    return body


def call_api(task, messages, stats, model=None, temperature=None, tools=None):
    """One logical attempt: up to MAX_HTTP_CALLS HTTP calls for 5xx (T1, T23)."""
    model = task.model if model is None else model
    temperature = task.temperature if temperature is None else temperature
    payload = json.dumps(
        request_body(task, messages, model, temperature, tools)).encode("utf-8")

    latency_ms = 0
    for _ in range(MAX_HTTP_CALLS):
        request = urllib.request.Request(
            task.endpoint, data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json"})
        started = time.time()
        stats.start_call(started)
        retryable = False
        try:
            with urllib.request.urlopen(request,
                                        timeout=REQUEST_TIMEOUT) as response:
                body = response.read()
            latency_ms = int(round((time.time() - started) * 1000))
            try:
                data = json.loads(body.decode("utf-8"))
                choice = data["choices"][0]
                if task.api_type == "completions":
                    message = None
                    content = choice["text"]        # not choice["message"]
                else:
                    message = choice["message"]
                    content = message["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                stats.end_call(time.time(), task_name=task.name)
                return Attempt(False, None, _meta(model, latency_ms))
            usage = data.get("usage") or {}
            meta = _meta(model, latency_ms, usage, choice.get("finish_reason"))
            stats.end_call(time.time(), meta["prompt_tokens"],
                           meta["completion_tokens"], task_name=task.name)
            return Attempt(True, content, meta, message)
        except urllib.error.HTTPError as exc:
            try:
                exc.read()
            except Exception:
                pass
            retryable = 500 <= exc.code < 600
        except Exception:
            # Transport-level failure (connection refused, timeout, ...): the
            # transient class, so retried like a 5xx (T23).
            retryable = True
        latency_ms = int(round((time.time() - started) * 1000))
        stats.end_call(time.time(), task_name=task.name)
        if not retryable:
            break
    return Attempt(False, None, _meta(model, latency_ms))


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

class ToolCall:
    """One tool call requested by the model, with its parsed arguments."""

    def __init__(self, name, args, call_id=None, error=None):
        self.name = name
        self.args = args
        self.call_id = call_id
        self.error = error          # set when `arguments` was not valid JSON


def parse_json_args(raw):
    """`function.arguments` -> (args, error).  The API sends a JSON string."""
    if isinstance(raw, dict):
        return raw, None
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}, None                                             # T76
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        return {}, "could not parse tool arguments as JSON: %s" % exc
    if not isinstance(parsed, dict):
        return {}, "tool arguments must be a JSON object"
    return parsed, None


def parse_tool_calls(task, attempt):
    """The tool calls of one response ([] when it is a final answer)."""
    if task.api_type == "completions":
        return parse_text_tool_calls(attempt.content)
    message = attempt.message or {}
    raw_calls = message.get("tool_calls") or []
    calls = []
    for index, raw in enumerate(raw_calls):
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") or {}
        args, error = parse_json_args(function.get("arguments"))
        calls.append(ToolCall(function.get("name"), args,
                              raw.get("id") or "call_%d" % index, error))
    return calls


def parse_text_tool_calls(text):
    """Tool calls written as `<tool_call>{...}</tool_call>` blocks (T77)."""
    calls = []
    for block in TOOL_CALL_RE.findall(text or ""):
        try:
            payload = json.loads(block)
        except ValueError as exc:
            calls.append(ToolCall(None, {},
                                  error="could not parse tool call as JSON: %s"
                                  % exc))
            continue
        if not isinstance(payload, dict):
            calls.append(ToolCall(None, {},
                                  error="tool call must be a JSON object"))
            continue
        args, error = parse_json_args(payload.get("arguments"))
        calls.append(ToolCall(payload.get("name"), args, error=error))
    return calls


def execute_tool_call(task, call):
    """Run one tool call -> the string result handed back to the model."""
    if call.error is not None:
        return "ERROR: %s" % call.error                             # T76
    for tool in task.tools:
        if tool.name == call.name:
            return tool.run(call.args)
    return "ERROR: unknown tool %r" % call.name                     # T78


def assistant_tool_message(task, attempt):
    """The assistant turn to append before the tool results."""
    if task.api_type == "completions":
        return {"role": "assistant", "content": attempt.content}
    return attempt.message


def tool_result_message(task, call, result):
    if task.api_type == "completions":
        return {"role": "tool", "content": result}
    return {"role": "tool", "tool_call_id": call.call_id,
            "content": result}                                      # T79


class AgenticLoop:
    """The outcome of one agentic loop: its output and its bookkeeping."""

    def __init__(self, output, iterations, tool_calls, detail, latency_ms,
                 finish_reason):
        self.output = output
        self.iterations = iterations
        self.tool_calls = tool_calls
        self.detail = detail
        self.latency_ms = latency_ms
        self.finish_reason = finish_reason

    def meta(self):
        """The aggregated agentic metadata object."""
        return {
            "total_prompt_tokens": sum(d["prompt_tokens"] or 0
                                       for d in self.detail),
            "total_completion_tokens": sum(d["completion_tokens"] or 0
                                           for d in self.detail),
            "total_tokens": sum(d["total_tokens"] or 0 for d in self.detail),
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "iterations_detail": self.detail,
        }


ITERATION_META_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens",
                       "latency_ms", "finish_reason")


def run_agentic_loop(task, row, setup, stats):
    """Call the API, run the tools it asks for, repeat until a final answer."""
    messages = build_messages(task, row, setup)
    started = time.time()
    detail = []
    records = []
    output = None
    finish_reason = None
    iterations = 0
    while iterations < task.max_iterations:
        attempt = call_api(task, messages, stats, tools=task.tools)
        iterations += 1                 # every request counts (spec)
        detail.append({key: attempt.meta[key] for key in ITERATION_META_KEYS})
        finish_reason = attempt.meta["finish_reason"]
        if not attempt.ok:
            break                       # retries exhausted: the loop ends (T80)
        calls = parse_tool_calls(task, attempt)
        if not calls:
            output = attempt.content    # final text, no tool calls
            break
        messages = messages + [assistant_tool_message(task, attempt)]
        for call in calls:
            result = execute_tool_call(task, call)
            records.append({"iteration": iterations, "tool": call.name,
                            "args": call.args, "result": result})
            messages.append(tool_result_message(task, call, result))
    else:
        finish_reason = "max_iterations"                            # spec
    latency_ms = int(round((time.time() - started) * 1000))
    return AgenticLoop(output, iterations, records, detail, latency_ms,
                       finish_reason)


# ---------------------------------------------------------------------------
# Row processing
# ---------------------------------------------------------------------------

class RowResult:
    def __init__(self, row, output, passed, extracted, metas, judge_score=None):
        self.row = row
        self.output = output
        self.passed = passed
        self.extracted = extracted
        self.metas = metas
        self.judge_score = judge_score

    @property
    def attempts(self):
        return len(self.metas)

    def to_json(self, task):
        metas = self.metas
        meta = metas[0] if len(metas) == 1 else metas              # T2
        output = None if self.output is None \
            else {task.output_field: self.output}
        result = {"passed": self.passed,
                  "extracted_answer": self.extracted,
                  "attempts": self.attempts}
        if task.evaluation and task.evaluation["type"] == "llm_judge":
            result["judge_score"] = self.judge_score
        return {
            "input": self.row,
            "output": output,
            "result": result,
            "meta": meta,
        }

    @property
    def solution_count(self):
        return 0 if self.output is None else 1

    @property
    def counts_as_passed(self):
        if self.passed is True:
            return True
        return self.passed is None and self.output is not None

    @property
    def counts_as_failed(self):
        return self.passed is False or self.output is None


class AgenticRowResult(RowResult):
    """A single-solution agentic row: one loop, one aggregated meta object."""

    def __init__(self, row, loop, passed, extracted, meta, judge_score=None):
        RowResult.__init__(self, row, loop.output, passed, extracted, [meta],
                           judge_score)
        self.loop = loop

    def to_json(self, task):
        data = RowResult.to_json(self, task)
        data["result"]["iterations"] = self.loop.iterations
        data["result"]["tool_calls"] = self.loop.tool_calls
        return data


class MultiRowResult:
    """A row in the Part 3 list format: many solutions, one meta per attempt."""

    def __init__(self, row, solutions, passed, metas):
        self.row = row
        self.solutions = solutions      # [(text, setup_name), ...]
        self.passed = passed
        self.metas = metas

    @property
    def attempts(self):
        return len(self.metas)

    @property
    def failed(self):
        return self.attempts - self.passed

    @property
    def solution_count(self):
        return len(self.solutions)

    def to_json(self, task):
        output = [{task.output_field: text, "icl_setup": setup_name}
                  for text, setup_name in self.solutions]           # T61
        return {
            "input": self.row,
            "output": output,
            "result": {"passed": self.passed, "failed": self.failed,
                       "attempts": self.attempts},                  # T47
            "meta": self.metas,
        }

    @property
    def counts_as_passed(self):
        return self.passed > 0                                      # T54

    @property
    def counts_as_failed(self):
        return self.passed == 0


def attempt_setups(task):
    """-> (setups, budget): the setup per attempt, and how many attempts.

    A `None` element (or a `None` list) means "no ICL": send the bare prompt.
    `setups` of None means the setup is picked per attempt by the strategy.
    """
    if task.scheme == "greedy":
        if task.icl is not None and task.num_solutions > 1:
            # Declared order, at most once per setup, whatever the strategy is.
            return list(task.icl.setups), len(task.icl.setups)
        # Nothing to vary without ICL, so one deterministic attempt (T49).
        return [task.icl.choose(0) if task.icl else None], 1
    if task.scheme in ("sample", "agentic"):
        return None, task.num_solutions                             # T81
    return None, task.attempt_limit                     # rejection


def process_row_multi(row, task, stats):
    """Collect solutions for one row in the Part 3 list format."""
    target = task.num_solutions
    gated = task.scheme == "rejection"   # only rejection filters on evaluation
    setups, budget = attempt_setups(task)

    solutions = []
    metas = []
    passed_count = 0
    for index in range(budget):
        if (passed_count if gated else len(solutions)) >= target:
            break
        if setups is not None:
            setup = setups[index]
        else:
            setup = task.icl.choose(index) if task.icl else None
        if task.scheme == "agentic":
            # One independent loop per solution; its aggregated metadata
            # becomes this attempt's meta entry (T82).
            loop = run_agentic_loop(task, row, setup, stats)
            content, meta, ok = loop.output, loop.meta(), loop.output is not None
        else:
            attempt = call_api(task, build_messages(task, row, setup), stats)
            content, meta, ok = attempt.content, attempt.meta, attempt.ok
        setup_name = setup.name if setup is not None else None
        meta["icl_setup"] = setup_name
        metas.append(meta)
        if not ok:
            # Retries exhausted: a spent attempt, not the end of the row (T51).
            meta["evaluation_passed"] = None if task.evaluation is None \
                else False                                          # T52
            continue
        passed, _extracted, _score, judge_meta = evaluate(
            content, row, task, stats)
        meta["evaluation_passed"] = passed          # None without evaluation
        if judge_meta is not None:
            meta["judge_meta"] = judge_meta                         # T36
        if passed:
            passed_count += 1
        if passed or not gated:                                     # T48
            solutions.append((content, setup_name))

    # Without an evaluation, "passing" is just "produced an output".
    reported = len(solutions) if task.evaluation is None else passed_count
    return MultiRowResult(row, solutions, reported, metas)


def process_row_agentic(row, task, stats):
    """A single-solution agentic row: one loop, evaluated on its final text."""
    loop = run_agentic_loop(task, row, None, stats)
    passed = extracted = judge_score = judge_meta = None
    if loop.output is not None:
        passed, extracted, judge_score, judge_meta = evaluate(
            loop.output, row, task, stats)
    elif task.evaluation is not None:
        passed = False          # no output, so evaluation fails (spec)
    meta = loop.meta()
    if judge_meta is not None:
        meta["judge_meta"] = judge_meta                             # T36
    return AgenticRowResult(row, loop, passed, extracted, meta, judge_score)


def process_row(row, task, stats):
    if not task.legacy:
        return process_row_multi(row, task, stats)
    if task.scheme == "agentic":
        return process_row_agentic(row, task, stats)
    messages = build_messages(task, row)
    limit = task.n if task.scheme == "rejection" else 1            # n ignored
    metas = []
    judge_score = None
    for _ in range(limit):
        attempt = call_api(task, messages, stats)
        metas.append(attempt.meta)
        if not attempt.ok:
            # Retries exhausted (or a non-retryable error): the row is done (T15)
            return RowResult(row, None, False, None, metas, judge_score)
        passed, extracted, judge_score, judge_meta = evaluate(
            attempt.content, row, task, stats)
        if judge_meta is not None:
            attempt.meta["judge_meta"] = judge_meta                 # T36
        if task.scheme != "rejection":
            return RowResult(row, attempt.content, passed, extracted, metas,
                             judge_score)
        if passed:
            return RowResult(row, attempt.content, True, extracted, metas,
                             judge_score)
    return RowResult(row, None, False, None, metas, judge_score)   # exhausted


def concurrency_for(rpm, row_count):
    """In-flight budget: saturate the server's rpm without unbounded threads."""
    return max(1, min(max(rpm, 4), MAX_CONCURRENCY, max(row_count, 1)))


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def interleave(tasks, inputs):
    """Round-robin job order so tasks really do interleave (T37)."""
    per_task = [[(task, index, row)
                 for index, row in enumerate(inputs[task.name])]
                for task in tasks]
    jobs = []
    for group in itertools.zip_longest(*per_task):
        jobs.extend(job for job in group if job is not None)
    return jobs


def run(tasks, inputs, outputs):
    """Run every task, write each output file, return the summary object."""
    stats = Stats()
    results = {task.name: [None] * len(inputs[task.name]) for task in tasks}
    jobs = interleave(tasks, inputs)

    if jobs:
        max_rpm = max(task.rpm for task in tasks)
        workers = concurrency_for(max_rpm, len(jobs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_row, row, task, stats):
                       (task.name, index) for task, index, row in jobs}
            for future, (name, index) in futures.items():
                results[name][index] = future.result()

    for task in tasks:
        path = outputs[task.name]
        try:
            with open(path, "w") as fh:
                for result in results[task.name]:
                    fh.write(json.dumps(result.to_json(task)) + "\n")
        except OSError as exc:
            raise UserError("cannot write output file %s: %s" % (path, exc))

    per_task = {}
    for task in tasks:
        rows = results[task.name]
        solutions = sum(r.solution_count for r in rows)
        per_task[task.name] = {
            "total": len(rows),
            "passed": sum(1 for r in rows if r.counts_as_passed),
            "failed": sum(1 for r in rows if r.counts_as_failed),
            "total_solutions": solutions,                           # T53
            "avg_solutions_per_input": round(solutions / len(rows), 2)
            if rows else 0.0,
            "total_api_calls": stats.task_calls(task.name),
        }

    elapsed = round(stats.elapsed, 1)
    # Reported throughput stays consistent with the reported elapsed time (T24);
    # on runs too short to round to 0.1s the raw time avoids a bogus 0.0.
    divisor = elapsed or stats.elapsed
    throughput = round(stats.api_calls / divisor * 60, 1) if divisor else 0.0
    return {
        "total": sum(t["total"] for t in per_task.values()),
        "passed": sum(t["passed"] for t in per_task.values()),
        "failed": sum(t["failed"] for t in per_task.values()),
        "total_prompt_tokens": stats.prompt_tokens,                # T38
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": elapsed,
        "throughput_rpm": throughput,
        "tasks": per_task,
    }


# ---------------------------------------------------------------------------
# CLI wiring: task selection, inputs, outputs
# ---------------------------------------------------------------------------

def select_task_names(names, requested):
    """Config order, filtered by --task (T39)."""
    if not requested:
        return list(names)
    unknown = [name for name in requested if name not in names]
    if unknown:
        raise UserError("--task %s is not defined in the config (known tasks: "
                        "%s)" % (unknown[0], ", ".join(names)))
    return [name for name in names if name in set(requested)]


def resolve_inputs(multi, names, selected, args):
    """-> {task_name: input path} for the selected tasks."""
    explicit = list(args.input or [])
    if explicit and args.input_dir:
        raise UserError("--input and --input-dir are alternative modes; "
                        "do not combine them")
    if not explicit and not args.input_dir:
        raise UserError("one of --input <path> or --input-dir <dir> is "
                        "required")

    if not multi:
        if args.input_dir:                                         # T40
            raise UserError("--input-dir requires a multi-task config; use "
                            "--input <path>")
        if len(explicit) > 1:
            raise UserError("--input may only be given once for a "
                            "single-task config")
        spec = explicit[0]
        name = selected[0]
        if "=" in spec and spec.split("=", 1)[0] == name:
            spec = spec.split("=", 1)[1]                           # T41
        return {name: spec}

    if explicit:
        mapping = {}
        for spec in explicit:
            if "=" not in spec:
                raise UserError("--input for a multi-task config must be "
                                "<task>=<path> (got %r)" % spec)
            name, path = spec.split("=", 1)
            if name not in names:
                raise UserError("--input names unknown task %r (known tasks: "
                                "%s)" % (name, ", ".join(names)))
            if not path:
                raise UserError("--input %s has an empty path" % name)
            mapping[name] = path
        # Unselected tasks are ignored entirely, inputs included.
        missing = [name for name in selected if name not in mapping]
        if missing:
            raise UserError("no --input given for task %r" % missing[0])
        return {name: mapping[name] for name in selected}

    directory = args.input_dir
    if not os.path.isdir(directory):
        raise UserError("input directory %s does not exist" % directory)
    mapping = {}
    for name in selected:
        path = os.path.join(directory, "%s.jsonl" % name)
        if not os.path.exists(path):
            raise UserError("input directory %s has no file %s.jsonl for "
                            "task %r" % (directory, name, name))
        mapping[name] = path
    return mapping


def resolve_outputs(multi, selected, output):
    """-> {task_name: output path}."""
    if not multi:
        return {selected[0]: output}
    if os.path.exists(output) and not os.path.isdir(output):        # T42
        raise UserError("--output must be a directory for a multi-task "
                        "config (%s is a file)" % output)
    if not os.path.exists(output):
        try:
            os.makedirs(output)
        except OSError as exc:
            raise UserError("cannot create output directory %s: %s"
                            % (output, exc))
    return {name: os.path.join(output, "%s.jsonl" % name) for name in selected}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class ArgumentParser(argparse.ArgumentParser):
    """Usage errors are configuration errors: exit 1, not argparse's 2 (T21)."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(1)


def build_parser():
    parser = ArgumentParser(prog="rejector.py",
                            description="Run prompting tasks over JSONL files.")
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="run a task")
    run_parser.add_argument("--config", required=True, help="YAML task config")
    run_parser.add_argument("--input", action="append", default=None,
                            help="JSONL input file, or <task>=<path>")
    run_parser.add_argument("--input-dir", dest="input_dir", default=None,
                            help="directory of <task_name>.jsonl files")
    run_parser.add_argument("--output", required=True,
                            help="JSONL output file, or output directory")
    run_parser.add_argument("--task", action="append", dest="task_names",
                            default=None, help="run only this task (repeatable)")
    run_parser.add_argument("--eval-model", dest="eval_model", default=None,
                            help="override the llm_judge model")
    run_parser.add_argument("--api-url", dest="api_url", default=None)
    run_parser.add_argument("--model", default=None)
    run_parser.add_argument("--rpm", type=int, default=None)
    run_parser.add_argument("--max-tokens", dest="max_tokens", type=int,
                            default=None)
    run_parser.add_argument("--scheme", choices=list(SCHEMES), default=None)
    run_parser.add_argument("--temperature", type=float, default=None)
    run_parser.add_argument("--n", type=int, default=None)
    run_parser.add_argument("--num-solutions", dest="num_solutions", type=int,
                            default=None,
                            help="solutions to collect per input row")
    run_parser.add_argument("--icl-strategy", dest="icl_strategy",
                            choices=list(ICL_STRATEGIES), default=None,
                            help="override icl.strategy")
    run_parser.add_argument("--icl-k", dest="icl_k", type=int, default=None,
                            help="override icl.k")
    run_parser.add_argument("--api-type", dest="api_type",
                            choices=list(API_TYPES), default=None,
                            help="override api_type")
    run_parser.add_argument("--chat-template", dest="chat_template",
                            choices=list(CHAT_TEMPLATES), default=None,
                            help="override chat_template (completions mode)")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_usage(sys.stderr)
        sys.stderr.write("error: a command is required (run)\n")
        return 1
    try:
        multi, raw_tasks = load_config(args.config)
        names = list(raw_tasks)
        selected = select_task_names(names, args.task_names)
        if not selected:
            raise UserError("no tasks selected")
        inputs = resolve_inputs(multi, names, selected, args)
        outputs = resolve_outputs(multi, selected, args.output)

        config_dir = os.path.dirname(os.path.abspath(args.config))
        tasks = []
        for name in selected:
            prefix = "tasks.%s" % name if multi else "task"
            tasks.append(build_task(raw_tasks[name], args, name=name,
                                    prefix=prefix, config_dir=config_dir))
        rows = {}
        for task in tasks:
            rows[task.name] = load_rows(inputs[task.name])
            validate_rows(rows[task.name], task)
        summary = run(tasks, rows, outputs)
    except UserError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
