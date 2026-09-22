#!/usr/bin/env python3
"""rejector.py - run YAML-configured generation tasks over JSONL inputs.

Reads a task config (single-task, or `defaults` + a `tasks` mapping) and one
JSONL input per task, sends one prompt per row to an OpenAI-compatible chat
completions API with enough requests in flight to use the configured request
budget, evaluates each response, and writes one JSONL result per input row.
"""
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

import aiohttp
import yaml

SCHEMES = ("greedy", "sample", "rejection", "agentic")
ICL_STRATEGIES = ("fixed", "random", "round_robin")
API_TYPES = ("chat", "completions")
CHAT_TEMPLATES = ("chatml", "llama3", "mistral", "zephyr")
TOOL_HANDLERS = ("echo", "static_map", "script")
EVAL_TYPES = ("exact_match", "contains", "regex", "llm_judge", "script")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")

# Total HTTP calls for one logical request: the original plus retries, ending
# on the third failure (see AMBIGUITIES.md T3).
MAX_HTTP_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.05

# Concurrency is sized from the configured rpm, which the spec describes as
# the server's approximate capacity; a little oversubscription keeps the
# server's internal queue fed without ever exceeding its capacity.
CONCURRENCY_FACTOR = 1.25
MIN_CONCURRENCY = 4
MAX_CONCURRENCY = 256

# Part 2: `script` evaluation commands are killed after this many seconds and
# the evaluation counts as a failure.
SCRIPT_TIMEOUT = 10.0
KILL_GRACE = 5.0

# Part 4: agentic defaults. A `script` tool handler is killed after
# TOOL_TIMEOUT seconds and reports the timeout as its result.
DEFAULT_MAX_ITERATIONS = 10
TOOL_TIMEOUT = 10.0
STATIC_MAP_DEFAULT = "NOT_FOUND"

RESPONSE_KEY = "__response__"
RESPONSE_PLACEHOLDER = "{%s}" % RESPONSE_KEY

# Thousands separators are part of the number: checkpoint 4's own example
# extracts `2730000` from "$2,730,000." (AMBIGUITIES.md T10).
NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
# A standalone uppercase answer choice: `A`, `(A)`, `A)`, `Answer: A` (the
# `A` of "Answer" is rejected because it is followed by a letter).
LETTER_RE = re.compile(r"(?<![A-Za-z])([A-D])(?![A-Za-z])")
PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
# Completions-mode tool calls arrive as text blocks, not as a native field.
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


class ConfigError(Exception):
    """Invalid configuration; exits 1."""


class InputError(Exception):
    """Invalid input file or row; exits 1."""


# --------------------------------------------------------------- config ---

class IclSetup(object):
    """One named in-context-learning setup, pre-rendered into chat turns."""

    def __init__(self, name, messages):
        self.name = name
        self.messages = messages


class IclConfig(object):
    def __init__(self, setups, strategy):
        self.setups = setups
        self.strategy = strategy

    def select(self, attempt_index):
        """The setup an attempt uses under the configured strategy."""
        if self.strategy == "fixed":
            return self.setups[0]
        if self.strategy == "round_robin":
            return self.setups[attempt_index % len(self.setups)]
        return random.choice(self.setups)


class TaskConfig(object):
    def __init__(self, name, api_url, model, rpm, system, user, scheme,
                 temperature, max_tokens, n, evaluation, output_field,
                 icl=None, num_solutions=1, max_attempts=None,
                 api_type="chat", chat_template="chatml", tools=None,
                 max_iterations=DEFAULT_MAX_ITERATIONS):
        self.name = name
        self.api_url = api_url
        self.model = model
        self.rpm = rpm
        self.system = system
        self.user = user
        self.scheme = scheme
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.n = n
        self.evaluation = evaluation
        self.output_field = output_field
        self.icl = icl
        self.num_solutions = num_solutions
        self.max_attempts = max_attempts
        self.api_type = api_type
        self.chat_template = chat_template
        self.tools = tools or []
        self.max_iterations = max_iterations

    @property
    def legacy(self):
        """Part 1 behavior: one solution, no ICL (see the spec's legacy rule)."""
        return self.num_solutions == 1 and self.icl is None

    @property
    def endpoint(self):
        if self.api_type == "completions":
            return self.api_url.rstrip("/") + "/v1/completions"
        return self.api_url.rstrip("/") + "/v1/chat/completions"

    @property
    def tools_by_name(self):
        return dict((tool.name, tool) for tool in self.tools)

    @property
    def concurrency(self):
        want = int(math.ceil(self.rpm * CONCURRENCY_FACTOR))
        return max(MIN_CONCURRENCY, min(MAX_CONCURRENCY, want))


def _require_text(value, label):
    if value is None:
        raise ConfigError("%s is required" % label)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("%s must be a non-empty string" % label)
    return value


def _require_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError("%s must be a number" % label)
    return value


def _require_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            return int(value)
        raise ConfigError("%s must be an integer" % label)
    return value


def load_config_file(path):
    if not os.path.exists(path):
        raise ConfigError("config file not found: %s" % path)
    try:
        with open(path) as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError("could not parse YAML config %s: %s" % (path, exc))
    except OSError as exc:
        raise ConfigError("could not read config %s: %s" % (path, exc))
    return raw


def merge_task(defaults, task):
    """Overlay one task on `defaults`; nested sections merge key by key."""
    merged = dict(defaults)
    for key, value in task.items():
        base = merged.get(key)
        if isinstance(value, dict) and isinstance(base, dict):
            nested = dict(base)
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def split_config(raw):
    """Returns (multi, [(name, task_mapping), ...]) in config order."""
    if not isinstance(raw, dict):
        raise ConfigError("config must be a YAML mapping with a 'task' or "
                          "'tasks' key")
    if "task" in raw:
        # A top-level `task` key is the Part 1 single-task format.
        task = raw.get("task")
        if not isinstance(task, dict):
            raise ConfigError("config must contain a 'task' mapping")
        name = task.get("name")
        if name is not None and not isinstance(name, str):
            raise ConfigError("task.name must be a string")
        return False, [(name or "task", task)]

    tasks = raw.get("tasks")
    if not isinstance(tasks, dict):
        raise ConfigError("config must contain a 'task' mapping or a 'tasks' "
                          "mapping")
    if not tasks:
        raise ConfigError("config 'tasks' mapping is empty")
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("config 'defaults' must be a mapping")

    specs = []
    for name, task in tasks.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("task names must be non-empty strings")
        if task is None:
            task = {}
        if not isinstance(task, dict):
            raise ConfigError("tasks.%s must be a mapping" % name)
        specs.append((name, merge_task(defaults, task)))
    return True, specs


def build_config(raw, args, config_dir=None):
    """Part 1 entry point: build the single TaskConfig from a raw config."""
    multi, specs = split_config(raw)
    name, task = specs[0]
    return build_task_config(task, args, name, multi, config_dir)


def build_task_config(task, args, name, multi=False, config_dir=None):
    """Validate one (already merged) task mapping into a TaskConfig."""
    label = ("tasks.%s" % name) if multi else "task"

    prompt = task.get("prompt") or {}
    if not isinstance(prompt, dict):
        raise ConfigError("%s.prompt must be a mapping" % label)
    generation = task.get("generation") or {}
    if not isinstance(generation, dict):
        raise ConfigError("%s.generation must be a mapping" % label)

    api_url = args.api_url if args.api_url is not None else task.get("api_url")
    model = args.model if args.model is not None else task.get("model")
    rpm = args.rpm if args.rpm is not None else task.get("rpm", 60)
    scheme = args.scheme if args.scheme is not None else generation.get("scheme", "greedy")
    temperature = (args.temperature if args.temperature is not None
                   else generation.get("temperature", 0.0))
    max_tokens = (args.max_tokens if args.max_tokens is not None
                  else generation.get("max_tokens", 512))
    n = args.n if args.n is not None else generation.get("n", 1)
    num_solutions = getattr(args, "num_solutions", None)
    if num_solutions is None:
        num_solutions = task.get("num_solutions", 1)
    num_solutions = _require_int(num_solutions, "%s.num_solutions" % label)
    if num_solutions < 1:
        raise ConfigError("%s.num_solutions must be >= 1" % label)

    api_url = _require_text(api_url, "%s.api_url" % label)
    model = _require_text(model, "%s.model" % label)
    user = _require_text(prompt.get("user"), "%s.prompt.user" % label)
    system = prompt.get("system")
    if system is not None and not isinstance(system, str):
        raise ConfigError("%s.prompt.system must be a string" % label)

    if scheme not in SCHEMES:
        raise ConfigError("%s.generation.scheme must be one of %s (got %r)"
                          % (label, ", ".join(SCHEMES), scheme))

    rpm = _require_number(rpm, "%s.rpm" % label)
    if rpm <= 0:
        raise ConfigError("%s.rpm must be greater than 0" % label)
    max_tokens = _require_int(max_tokens, "%s.generation.max_tokens" % label)
    if max_tokens <= 0:
        raise ConfigError("%s.generation.max_tokens must be greater than 0" % label)
    temperature = float(_require_number(temperature, "%s.generation.temperature" % label))

    if scheme == "greedy":
        # greedy forces temperature to 0.0 and ignores n.
        temperature = 0.0
        n = 1
    elif scheme == "sample":
        if temperature <= 0:
            raise ConfigError("%s.generation.temperature must be > 0 for "
                              "scheme 'sample'" % label)
        n = 1
    elif scheme == "agentic":
        # The loop makes one request at a time; `n` has no meaning here, and
        # the spec's own example runs the loop at temperature 0.0.
        n = 1
    else:  # rejection
        if temperature <= 0:
            raise ConfigError("%s.generation.temperature must be > 0 for "
                              "scheme 'rejection'" % label)
        n = _require_int(n, "%s.generation.n" % label)
        if n < 1:
            raise ConfigError("%s.generation.n must be >= 1 for scheme "
                              "'rejection'" % label)

    eval_model = getattr(args, "eval_model", None)
    evaluation = build_evaluation(task.get("evaluation"), scheme, label,
                                  model, eval_model)

    output_field = task.get("output_field", "output")
    output_field = _require_text(output_field, "%s.output_field" % label)

    icl = build_icl(task.get("icl"), args, label, user, config_dir)

    # Part 4: transport (chat vs completions), the prompt template, the tool
    # catalogue, and the agentic iteration budget.
    api_type = getattr(args, "api_type", None) or task.get("api_type", "chat")
    if api_type not in API_TYPES:
        raise ConfigError("%s.api_type must be one of %s (got %r)"
                          % (label, ", ".join(API_TYPES), api_type))
    chat_template = (getattr(args, "chat_template", None)
                     or task.get("chat_template", "chatml"))
    if chat_template not in CHAT_TEMPLATES:
        raise ConfigError("%s.chat_template must be one of %s (got %r)"
                          % (label, ", ".join(CHAT_TEMPLATES), chat_template))
    max_iterations = _require_int(
        generation.get("max_iterations", DEFAULT_MAX_ITERATIONS),
        "%s.generation.max_iterations" % label)
    if max_iterations < 1:
        raise ConfigError("%s.generation.max_iterations must be >= 1" % label)
    tools = build_tools(task.get("tools"), label)

    max_attempts = generation.get("max_attempts")
    if max_attempts is not None:
        max_attempts = _require_int(max_attempts,
                                    "%s.generation.max_attempts" % label)
        if max_attempts < 1:
            raise ConfigError("%s.generation.max_attempts must be >= 1" % label)
    else:
        max_attempts = 3 * num_solutions

    return TaskConfig(name, api_url, model, rpm, system, user, scheme,
                      temperature, max_tokens, n, evaluation, output_field,
                      icl, num_solutions, max_attempts, api_type,
                      chat_template, tools, max_iterations)


def build_evaluation(raw, scheme, label="task", task_model=None,
                     eval_model=None):
    """Validate the evaluation block; returns a normalised dict or None."""
    if raw is None:
        if scheme == "rejection":
            raise ConfigError("%s.evaluation is required for scheme "
                              "'rejection'" % label)
        return None
    if not isinstance(raw, dict):
        raise ConfigError("%s.evaluation must be a mapping" % label)

    eval_type = raw.get("type")
    if eval_type not in EVAL_TYPES:
        raise ConfigError("%s.evaluation.type must be one of %s (got %r)"
                          % (label, ", ".join(EVAL_TYPES), eval_type))

    # A judge response is a bare score, so `first_number` is its default.
    default_extract = "first_number" if eval_type == "llm_judge" else "full"
    extract = raw.get("extract", default_extract)
    if extract not in EXTRACT_METHODS:
        raise ConfigError("%s.evaluation.extract must be one of %s (got %r)"
                          % (label, ", ".join(EXTRACT_METHODS), extract))

    evaluation = {"type": eval_type, "extract": extract, "answer_field": None,
                  "pattern": None, "command_template": None,
                  "success_exit_code": 0, "judge_system": None,
                  "judge_user": None, "threshold": None, "model": None}

    if eval_type in ("exact_match", "contains"):
        evaluation["answer_field"] = _require_text(
            raw.get("answer_field"),
            "%s.evaluation.answer_field (required for type '%s')"
            % (label, eval_type))
    elif eval_type == "regex":
        pattern = _require_text(
            raw.get("pattern"),
            "%s.evaluation.pattern (required for type 'regex')" % label)
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError("%s.evaluation.pattern is not a valid regular "
                              "expression: %s" % (label, exc))
        evaluation["pattern"] = pattern
    elif eval_type == "script":
        evaluation["command_template"] = _require_text(
            raw.get("command_template"),
            "%s.evaluation.command_template (required for type 'script')"
            % label)
        exit_code = raw.get("success_exit_code", 0)
        evaluation["success_exit_code"] = _require_int(
            exit_code, "%s.evaluation.success_exit_code" % label)
    else:  # llm_judge
        judge_prompt = raw.get("judge_prompt")
        if not isinstance(judge_prompt, dict):
            raise ConfigError("%s.evaluation.judge_prompt must be a mapping "
                              "(required for type 'llm_judge')" % label)
        evaluation["judge_user"] = _require_text(
            judge_prompt.get("user"), "%s.evaluation.judge_prompt.user" % label)
        judge_system = judge_prompt.get("system")
        if judge_system is not None and not isinstance(judge_system, str):
            raise ConfigError("%s.evaluation.judge_prompt.system must be a "
                              "string" % label)
        evaluation["judge_system"] = judge_system
        threshold = raw.get("threshold")
        if threshold is None:
            raise ConfigError("%s.evaluation.threshold is required for type "
                              "'llm_judge'" % label)
        evaluation["threshold"] = _require_number(
            threshold, "%s.evaluation.threshold" % label)
        model = raw.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise ConfigError("%s.evaluation.model must be a non-empty string"
                              % label)
        # --eval-model beats the config, which beats the task's own model.
        evaluation["model"] = eval_model or model or task_model

    return evaluation


# ------------------------------------------------------------------ icl ---

def _icl_example(raw, label):
    """Validate one `{"input": <object>, "output": <string>}` example."""
    if not isinstance(raw, dict):
        raise ConfigError("%s must be a mapping with 'input' and 'output'"
                          % label)
    if "input" not in raw:
        raise ConfigError("%s is missing 'input'" % label)
    if "output" not in raw:
        raise ConfigError("%s is missing 'output'" % label)
    if not isinstance(raw["input"], dict):
        raise ConfigError("%s.input must be an object" % label)
    if not isinstance(raw["output"], str):
        raise ConfigError("%s.output must be a string" % label)
    return {"input": raw["input"], "output": raw["output"]}


def load_icl_file(path, label):
    """Read a JSONL ICL file; every non-empty line must be a valid example."""
    if not os.path.exists(path):
        raise ConfigError("%s file not found: %s" % (label, path))
    examples = []
    try:
        with open(path) as handle:
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    raise ConfigError("%s line %d is not valid JSON: %s"
                                      % (label, lineno, exc))
                examples.append(_icl_example(obj, "%s line %d" % (label, lineno)))
    except OSError as exc:
        raise ConfigError("could not read %s file %s: %s" % (label, path, exc))
    return examples


def build_icl(raw, args, label, user_template, config_dir):
    """Validate the `icl` block into an IclConfig (or None when absent)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("%s.icl must be a mapping" % label)

    setups_raw = raw.get("setups")
    if not isinstance(setups_raw, list) or not setups_raw:
        raise ConfigError("%s.icl.setups must be a non-empty list" % label)

    k = getattr(args, "icl_k", None)
    if k is None:
        k = raw.get("k")
    if k is not None:
        k = _require_int(k, "%s.icl.k" % label)
        if k < 1:
            raise ConfigError("%s.icl.k must be >= 1" % label)

    strategy = getattr(args, "icl_strategy", None)
    if strategy is None:
        strategy = raw.get("strategy", "fixed")
    if strategy not in ICL_STRATEGIES:
        raise ConfigError("%s.icl.strategy must be one of %s (got %r)"
                          % (label, ", ".join(ICL_STRATEGIES), strategy))

    setups = []
    for index, setup_raw in enumerate(setups_raw):
        setup_label = "%s.icl.setups[%d]" % (label, index)
        if not isinstance(setup_raw, dict):
            raise ConfigError("%s must be a mapping" % setup_label)
        name = _require_text(setup_raw.get("name"), "%s.name" % setup_label)
        has_examples = "examples" in setup_raw
        has_file = "file" in setup_raw
        if has_examples == has_file:
            raise ConfigError("%s must have exactly one of 'examples' or "
                              "'file'" % setup_label)
        if has_examples:
            raw_examples = setup_raw["examples"]
            if not isinstance(raw_examples, list):
                raise ConfigError("%s.examples must be a list" % setup_label)
            examples = [_icl_example(item, "%s.examples[%d]"
                                     % (setup_label, position))
                        for position, item in enumerate(raw_examples)]
        else:
            path = _require_text(setup_raw["file"], "%s.file" % setup_label)
            if not os.path.isabs(path):
                path = os.path.join(config_dir or "", path)
            examples = load_icl_file(path, "%s.file" % setup_label)
        if k is not None:
            examples = examples[:k]
        setups.append(IclSetup(name, icl_messages(examples, user_template,
                                                  setup_label)))
    return IclConfig(setups, strategy)


def icl_messages(examples, user_template, label):
    """Render examples as alternating user/assistant turns."""
    messages = []
    for position, example in enumerate(examples):
        try:
            content = render_template(user_template, example["input"], 0)
        except InputError as exc:
            raise ConfigError("%s.examples[%d]: cannot render prompt.user: %s"
                              % (label, position, exc))
        messages.append({"role": "user", "content": content})
        messages.append({"role": "assistant", "content": example["output"]})
    return messages


def messages_for(base, setup):
    """Splice a setup's example turns in front of the final user message."""
    if setup is None or not setup.messages:
        return base
    return base[:-1] + list(setup.messages) + base[-1:]


# ---------------------------------------------------------------- input ---

def load_rows(path):
    if not os.path.exists(path):
        raise InputError("input file not found: %s" % path)
    rows = []
    try:
        with open(path) as handle:
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    raise InputError("input line %d is not valid JSON: %s"
                                     % (lineno, exc))
                if not isinstance(obj, dict):
                    raise InputError("input line %d is not a JSON object"
                                     % lineno)
                rows.append(obj)
    except OSError as exc:
        raise InputError("could not read input %s: %s" % (path, exc))
    return rows


def to_text(value):
    """Render a row value as text for prompts and comparisons."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_template(template, row, row_index, extra=None):
    """Substitute {field} placeholders from `row` (and `extra`)."""
    missing = []

    def replace(match):
        field = match.group(1)
        if extra is not None and field in extra:
            return to_text(extra[field])
        if field not in row:
            missing.append(field)
            return match.group(0)
        return to_text(row[field])

    rendered = PLACEHOLDER_RE.sub(replace, template)
    if missing:
        raise InputError("row %d: missing field '%s'" % (row_index, missing[0]))
    return rendered


def render_command(template, row, response, row_index):
    """Render a script command; row text may itself carry {__response__}."""
    rendered = render_template(template, row, row_index,
                               {RESPONSE_KEY: response})
    if RESPONSE_PLACEHOLDER in rendered:
        # A row field such as {test_code} expanded to text containing
        # {__response__}; substitute it before the command is executed.
        rendered = rendered.replace(RESPONSE_PLACEHOLDER, to_text(response))
    return rendered


def check_fields(template, row, row_index):
    """Fail fast on placeholders a row cannot fill (ignoring __response__)."""
    for match in PLACEHOLDER_RE.finditer(template):
        field = match.group(1)
        if field == RESPONSE_KEY:
            continue
        if field not in row:
            raise InputError("row %d: missing field '%s'" % (row_index, field))


def build_messages(cfg, rows):
    """Render every row up front so input errors abort before any request."""
    prepared = []
    evaluation = cfg.evaluation or {}
    answer_field = evaluation.get("answer_field")
    for index, row in enumerate(rows):
        messages = []
        if cfg.system is not None:
            messages.append({"role": "system",
                             "content": render_template(cfg.system, row, index)})
        messages.append({"role": "user",
                         "content": render_template(cfg.user, row, index)})
        if answer_field is not None and answer_field not in row:
            raise InputError("row %d: missing field '%s'" % (index, answer_field))
        if evaluation.get("command_template"):
            check_fields(evaluation["command_template"], row, index)
        if evaluation.get("judge_user"):
            check_fields(evaluation["judge_user"], row, index)
        if evaluation.get("judge_system"):
            check_fields(evaluation["judge_system"], row, index)
        prepared.append(messages)
    return prepared


# ----------------------------------------------------------- evaluation ---

def extract_answer(text, method):
    """Pull the comparison value out of a response body."""
    if text is None:
        return None
    if method == "full":
        return text
    if method == "last_line":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else ""
    if method == "last_number":
        matches = NUMBER_RE.findall(text)
        return matches[-1].replace(",", "") if matches else None
    if method == "first_number":
        match = NUMBER_RE.search(text)
        return match.group(0).replace(",", "") if match else None
    if method == "letter":
        match = LETTER_RE.search(text)
        return match.group(1) if match else None
    raise ConfigError("unknown extract method: %r" % method)


def to_number(text):
    """Parse an extracted number; int when it has no fractional part."""
    if text is None:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if value.is_integer() and "." not in text:
        return int(value)
    return value


def evaluate(text, row, evaluation):
    """Returns (passed, extracted_answer) for one non-async evaluation."""
    if evaluation is None:
        return None, None
    extracted = extract_answer(text, evaluation["extract"])
    eval_type = evaluation["type"]
    if eval_type == "exact_match":
        expected = to_text(row.get(evaluation["answer_field"]))
        passed = (extracted is not None
                  and extracted.strip() == expected.strip())
    elif eval_type == "contains":
        expected = to_text(row.get(evaluation["answer_field"]))
        passed = expected in text
    else:  # regex
        passed = re.search(evaluation["pattern"], text) is not None
    return bool(passed), extracted


async def run_script_eval(evaluation, row, response, row_index):
    """Run a `script` evaluation; returns True when the exit code matches."""
    command = render_command(evaluation["command_template"], row, response,
                             row_index)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Own process group: a timeout can then take the shell and every
            # process it spawned, not just the shell.
            start_new_session=True)
    except OSError:
        return False
    try:
        # stdout/stderr are captured but deliberately not reported anywhere.
        await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT)
    except asyncio.TimeoutError:
        _kill_process_group(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE)
        except (asyncio.TimeoutError, ProcessLookupError, OSError):
            pass
        return False
    return proc.returncode == evaluation["success_exit_code"]


def _kill_process_group(proc):
    """SIGKILL the timed-out command's whole process group, by pid."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


# ----------------------------------------------------------------- tools ---

class ToolSpec(object):
    """One tool an agentic task may call, with its handler configuration."""

    def __init__(self, name, description, parameters, handler):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    @property
    def function(self):
        """The tool definition as an OpenAI `function` object."""
        function = {"name": self.name}
        if self.description is not None:
            function["description"] = self.description
        if self.parameters is not None:
            function["parameters"] = self.parameters
        return function

    @property
    def definition(self):
        """The entry sent in a chat request's `tools` array."""
        return {"type": "function", "function": self.function}

    @property
    def lookup_field(self):
        """The `static_map` key: the first required parameter (T66)."""
        parameters = self.parameters or {}
        required = parameters.get("required")
        if isinstance(required, list) and required:
            return required[0]
        properties = parameters.get("properties")
        if isinstance(properties, dict) and properties:
            return list(properties)[0]
        return None


def build_tools(raw, label):
    """Validate the task's `tools` list into ToolSpecs."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError("%s.tools must be a list" % label)
    tools = []
    seen = set()
    for index, item in enumerate(raw):
        tool_label = "%s.tools[%d]" % (label, index)
        if not isinstance(item, dict):
            raise ConfigError("%s must be a mapping" % tool_label)
        name = _require_text(item.get("name"), "%s.name" % tool_label)
        if name in seen:
            raise ConfigError("%s.name is already used: %r" % (tool_label, name))
        seen.add(name)
        description = item.get("description")
        if description is not None and not isinstance(description, str):
            raise ConfigError("%s.description must be a string" % tool_label)
        parameters = item.get("parameters")
        if parameters is not None and not isinstance(parameters, dict):
            raise ConfigError("%s.parameters must be a mapping" % tool_label)
        handler = build_handler(item.get("handler"), "%s.handler" % tool_label)
        tools.append(ToolSpec(name, description, parameters, handler))
    return tools


def build_handler(raw, label):
    """Validate one tool handler block into a normalised dict."""
    if not isinstance(raw, dict):
        raise ConfigError("%s is required and must be a mapping" % label)
    kind = raw.get("type")
    if kind not in TOOL_HANDLERS:
        raise ConfigError("%s.type must be one of %s (got %r)"
                          % (label, ", ".join(TOOL_HANDLERS), kind))
    handler = {"type": kind}
    if kind == "static_map":
        mapping = raw.get("mapping")
        if not isinstance(mapping, dict):
            raise ConfigError("%s.mapping is required for handler type "
                              "'static_map' and must be a mapping" % label)
        handler["mapping"] = dict((to_text(key), to_text(value))
                                  for key, value in mapping.items())
        handler["default"] = to_text(raw.get("default", STATIC_MAP_DEFAULT))
    elif kind == "script":
        handler["command"] = _require_text(
            raw.get("command"),
            "%s.command (required for handler type 'script')" % label)
        handler["arg_field"] = _require_text(
            raw.get("arg_field"),
            "%s.arg_field (required for handler type 'script')" % label)
        timeout = _require_number(raw.get("timeout", TOOL_TIMEOUT),
                                  "%s.timeout" % label)
        if timeout <= 0:
            raise ConfigError("%s.timeout must be greater than 0" % label)
        handler["timeout"] = float(timeout)
    return handler


class ToolCall(object):
    """One tool call requested by the model, with its arguments parsed."""

    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.name = name
        self.args = parse_tool_args(arguments)


def parse_tool_args(arguments):
    """`function.arguments` is JSON on the wire; unparsable means no args."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def parse_chat_tool_calls(message):
    """Tool calls from an OpenAI chat message's `tool_calls` array."""
    raw = message.get("tool_calls")
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
        if not isinstance(name, str):
            continue
        call_id = item.get("id") or "call_%d" % (index + 1)
        calls.append(ToolCall(call_id, name, function.get("arguments")))
    return calls


def parse_text_tool_calls(text):
    """Tool calls from `<tool_call>{...}</tool_call>` blocks in a completion."""
    calls = []
    for index, block in enumerate(TOOL_CALL_RE.findall(text or "")):
        try:
            obj = json.loads(block)
        except ValueError:
            continue
        if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
            continue
        calls.append(ToolCall("call_%d" % (index + 1), obj["name"],
                              obj.get("arguments")))
    return calls


async def execute_tool(tools, name, args):
    """Run one tool call's handler and return its string result."""
    tool = tools.get(name)
    if tool is None:
        return "ERROR: unknown tool %r" % name
    handler = tool.handler
    kind = handler["type"]
    if kind == "echo":
        return json.dumps(args, ensure_ascii=False)
    if kind == "static_map":
        field = tool.lookup_field
        if isinstance(args, dict) and field is not None and field in args:
            key = to_text(args[field])
        elif isinstance(args, dict) and args:
            key = to_text(list(args.values())[0])
        else:
            return handler["default"]
        return handler["mapping"].get(key, handler["default"])
    return await run_script_handler(handler, args)


async def run_script_handler(handler, args):
    """Run `command <arg_field value>`; stdout, or `ERROR: ...` on failure."""
    value = ""
    if isinstance(args, dict) and handler["arg_field"] in args:
        value = to_text(args[handler["arg_field"]])
    try:
        argv = shlex.split(handler["command"])
    except ValueError as exc:
        return "ERROR: %s" % exc
    if not argv:
        return "ERROR: empty command"
    try:
        proc = await asyncio.create_subprocess_exec(
            *(argv + [value]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Own process group, so a timeout takes any children too.
            start_new_session=True)
    except (OSError, ValueError) as exc:
        return "ERROR: %s" % exc
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(),
                                                timeout=handler["timeout"])
    except asyncio.TimeoutError:
        _kill_process_group(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE)
        except (asyncio.TimeoutError, ProcessLookupError, OSError):
            pass
        return ("ERROR: command timed out after %g seconds"
                % handler["timeout"])
    if proc.returncode != 0:
        message = (stderr.decode("utf-8", "replace").strip()
                   or "command exited with status %d" % proc.returncode)
        return "ERROR: %s" % message
    return stdout.decode("utf-8", "replace").strip()


class AgenticRun(object):
    """The outcome of one agentic loop."""

    def __init__(self, content, iterations, tool_calls, metas, latency_ms,
                 finish_reason):
        self.content = content
        self.iterations = iterations
        self.tool_calls = tool_calls
        self.metas = metas
        self.latency_ms = latency_ms
        self.finish_reason = finish_reason

    @property
    def meta(self):
        """Loop metadata, aggregated over the iterations that answered."""
        if not self.metas:
            # No response at all, so there is nothing to report (T2).
            return None
        detail = [{
            "prompt_tokens": meta["prompt_tokens"],
            "completion_tokens": meta["completion_tokens"],
            "total_tokens": meta["total_tokens"],
            "latency_ms": meta["latency_ms"],
            "finish_reason": meta["finish_reason"],
        } for meta in self.metas]
        return {
            "total_prompt_tokens": sum(m["prompt_tokens"] for m in self.metas),
            "total_completion_tokens": sum(m["completion_tokens"]
                                           for m in self.metas),
            "total_tokens": sum(m["total_tokens"] for m in self.metas),
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "iterations_detail": detail,
        }


# ------------------------------------------------------- chat templates ---

# (prefix, per-message turn, generation suffix) for the marker templates.
TEMPLATE_TURNS = {
    "chatml": ("", "<|im_start|>%s\n%s<|im_end|>\n", "<|im_start|>assistant\n"),
    "llama3": ("<|begin_of_text|>",
               "<|start_header_id|>%s<|end_header_id|>\n\n%s<|eot_id|>",
               "<|start_header_id|>assistant<|end_header_id|>\n\n"),
    "zephyr": ("", "<|%s|>\n%s</s>\n", "<|assistant|>\n"),
}

TOOL_PROMPT = """You have access to the following tools:

%s

To call a tool, reply with a block of the form:
<tool_call>
{"name": "<tool name>", "arguments": {"<argument>": "<value>"}}
</tool_call>

Emit one block per tool call. When you have the final answer, reply with plain text and no tool call."""


def message_content(message):
    content = message.get("content")
    return content if isinstance(content, str) else ""


def inject_tool_prompt(messages, tools):
    """Completions mode has no `tools` field: describe them in the prompt."""
    messages = list(messages)
    if not tools:
        return messages
    listing = "\n".join(json.dumps(tool.function, ensure_ascii=False)
                        for tool in tools)
    block = TOOL_PROMPT % listing
    if messages and messages[0].get("role") == "system":
        head = dict(messages[0])
        head["content"] = "%s\n\n%s" % (message_content(head), block)
        return [head] + messages[1:]
    return [{"role": "system", "content": block}] + messages


def render_prompt(messages, template, tools=None):
    """Render a conversation into one prompt string for /v1/completions."""
    messages = inject_tool_prompt(messages, tools)
    if template == "mistral":
        return render_mistral(messages)
    prefix, turn, generation = TEMPLATE_TURNS[template]
    parts = [prefix]
    for message in messages:
        parts.append(turn % (message.get("role") or "user",
                             message_content(message)))
    parts.append(generation)
    return "".join(parts)


def render_mistral(messages):
    """Mistral has no role markers: the system prompt leads the first [INST]."""
    system = "\n\n".join(message_content(m) for m in messages
                         if m.get("role") == "system" and message_content(m))
    parts = []
    pending = []
    used_system = []

    def flush():
        text = "\n\n".join(item for item in pending if item)
        del pending[:]
        if system and not used_system:
            used_system.append(True)
            text = (system + "\n\n" + text) if text else system
        elif not text:
            return
        parts.append("[INST] %s [/INST]" % text)

    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        if role == "assistant":
            flush()
            parts.append("%s</s>" % message_content(message))
        else:
            # user and tool turns both become instruction content.
            pending.append(message_content(message))
    flush()
    return "".join(parts)


# ------------------------------------------------------------- pipeline ---

class Stats(object):
    def __init__(self):
        self.api_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.first_request = None
        self.last_response = None

    def opened(self, when):
        self.api_calls += 1
        if self.first_request is None or when < self.first_request:
            self.first_request = when

    def closed(self, when):
        if self.last_response is None or when > self.last_response:
            self.last_response = when

    @property
    def elapsed(self):
        if self.first_request is None or self.last_response is None:
            return 0.0
        return max(0.0, self.last_response - self.first_request)

    @classmethod
    def combine(cls, parts):
        total = cls()
        for part in parts:
            total.api_calls += part.api_calls
            total.prompt_tokens += part.prompt_tokens
            total.completion_tokens += part.completion_tokens
            if part.first_request is not None and (
                    total.first_request is None
                    or part.first_request < total.first_request):
                total.first_request = part.first_request
            if part.last_response is not None:
                total.closed(part.last_response)
        return total


def _token(usage, key):
    value = usage.get(key) if isinstance(usage, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


class Reply(object):
    """One successful model response: its text, tool calls, and metadata."""

    def __init__(self, content, tool_calls, message, meta):
        self.content = content
        self.tool_calls = tool_calls
        self.message = message
        self.meta = meta


class Runner(object):
    def __init__(self, cfg, session, semaphore, stats):
        self.cfg = cfg
        self.session = session
        self.semaphore = semaphore
        self.stats = stats
        self.tools = cfg.tools_by_name

    def build_payload(self, messages, model, tools):
        """The request body for this task's api_type."""
        cfg = self.cfg
        if cfg.api_type == "completions":
            return {
                "model": model,
                "prompt": render_prompt(messages, cfg.chat_template, tools),
                "temperature": cfg.temperature,
                "max_tokens": cfg.max_tokens,
            }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }
        if tools:
            payload["tools"] = [tool.definition for tool in tools]
        return payload

    async def request(self, messages, model=None, tools=None):
        """One logical request, with retries. Returns a Reply or None."""
        model = model or self.cfg.model
        payload = self.build_payload(messages, model, tools)
        for attempt in range(MAX_HTTP_ATTEMPTS):
            retryable, reply = await self._post_once(payload, model)
            if reply is not None:
                return reply
            if not retryable:
                return None
            if attempt < MAX_HTTP_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        return None

    async def call_api(self, messages, model=None):
        """A request whose response must be final text. (content, meta)/None."""
        reply = await self.request(messages, model=model)
        if reply is None or not isinstance(reply.content, str):
            return None
        return reply.content, reply.meta

    async def _post_once(self, payload, model):
        """Returns (retryable, Reply or None)."""
        async with self.semaphore:
            start = time.monotonic()
            self.stats.opened(start)
            try:
                async with self.session.post(self.cfg.endpoint,
                                             json=payload) as response:
                    status = response.status
                    body = await response.text()
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                self.stats.closed(time.monotonic())
                return True, None
            end = time.monotonic()
            self.stats.closed(end)

        if status >= 500:
            return True, None
        if not 200 <= status < 300:
            return False, None

        try:
            data = json.loads(body)
            choice = data["choices"][0]
            if not isinstance(choice, dict):
                raise ValueError("choice is not an object")
            if self.cfg.api_type == "completions":
                content = choice["text"]
                if not isinstance(content, str):
                    raise ValueError("text is not a string")
                message = {"role": "assistant", "content": content}
                tool_calls = parse_text_tool_calls(content)
            else:
                message = choice["message"]
                if not isinstance(message, dict):
                    raise ValueError("message is not an object")
                content = message.get("content")
                tool_calls = parse_chat_tool_calls(message)
                if not isinstance(content, str) and not tool_calls:
                    # A response with neither text nor tool calls is unusable.
                    raise ValueError("content is not a string")
        except (ValueError, KeyError, IndexError, TypeError):
            return False, None

        usage = data.get("usage") or {}
        meta = {
            "model": model,
            "prompt_tokens": _token(usage, "prompt_tokens"),
            "completion_tokens": _token(usage, "completion_tokens"),
            "total_tokens": _token(usage, "total_tokens"),
            "latency_ms": int(round((end - start) * 1000)),
            "finish_reason": choice.get("finish_reason"),
        }
        self.stats.prompt_tokens += meta["prompt_tokens"]
        self.stats.completion_tokens += meta["completion_tokens"]
        return False, Reply(content, tool_calls, message, meta)

    async def judge(self, row, response, row_index):
        """Returns (passed, extracted, judge_score, judge_meta)."""
        evaluation = self.cfg.evaluation
        extra = {RESPONSE_KEY: response}
        messages = []
        if evaluation["judge_system"] is not None:
            messages.append({
                "role": "system",
                "content": render_template(evaluation["judge_system"], row,
                                           row_index, extra)})
        messages.append({
            "role": "user",
            "content": render_template(evaluation["judge_user"], row,
                                       row_index, extra)})
        outcome = await self.call_api(messages, model=evaluation["model"])
        if outcome is None:
            return False, None, None, None
        text, meta = outcome
        extracted = extract_answer(text, evaluation["extract"])
        score = to_number(extracted)
        passed = score is not None and score >= evaluation["threshold"]
        return bool(passed), extracted, score, meta

    async def evaluate_response(self, content, row, row_index):
        """Returns (passed, extracted, judge_score, judge_meta)."""
        evaluation = self.cfg.evaluation
        if evaluation is None:
            return None, None, None, None
        if evaluation["type"] == "script":
            passed = await run_script_eval(evaluation, row, content, row_index)
            return bool(passed), None, None, None
        if evaluation["type"] == "llm_judge":
            return await self.judge(row, content, row_index)
        passed, extracted = evaluate(content, row, evaluation)
        return passed, extracted, None, None

    async def run_row(self, row, messages, row_index):
        """Produce the output record for one input row."""
        if self.cfg.scheme == "agentic":
            if self.cfg.legacy:
                return await self.run_agentic_row(row, messages, row_index)
            return await self.run_agentic_multi(row, messages, row_index)
        if not self.cfg.legacy:
            return await self.run_row_multi(row, messages, row_index)
        max_attempts = self.cfg.n if self.cfg.scheme == "rejection" else 1
        metas = []
        attempts = 0
        judge_score = None
        for _ in range(max_attempts):
            attempts += 1
            outcome = await self.call_api(messages)
            if outcome is None:
                # The request never produced a response: the row has failed.
                return self._record(row, None, False, None, attempts, metas,
                                    judge_score)
            content, meta = outcome
            passed, extracted, judge_score, judge_meta = \
                await self.evaluate_response(content, row, row_index)
            if self.is_judge:
                meta["judge_meta"] = judge_meta
            metas.append(meta)
            if self.cfg.scheme != "rejection" or passed:
                return self._record(row, content, passed, extracted, attempts,
                                    metas, judge_score)
        # Rejection sampling exhausted every attempt without a passing response.
        return self._record(row, None, False, None, attempts, metas, judge_score)

    def _attempt_plan(self):
        """(budget, setup picker) for one row under the current scheme."""
        cfg = self.cfg
        icl = cfg.icl
        if cfg.scheme == "greedy":
            if icl is None:
                # One deterministic prompt: one attempt, however many
                # solutions were asked for (AMBIGUITIES.md T47).
                return 1, lambda index: None
            if cfg.num_solutions > 1:
                # Declared order, each setup at most once; the strategy is
                # ignored because repeating a setup cannot add information.
                setups = list(icl.setups)
                return len(setups), lambda index: setups[index]
            return 1, lambda index: icl.select(index)
        if cfg.scheme == "sample":
            return cfg.num_solutions, lambda index: (
                None if icl is None else icl.select(index))
        return cfg.max_attempts, lambda index: (
            None if icl is None else icl.select(index))

    async def run_row_multi(self, row, base, row_index):
        """The Part 3 record: a list of solutions, results, and metadata."""
        cfg = self.cfg
        gated = cfg.scheme == "rejection"
        budget, pick = self._attempt_plan()
        outputs = []
        metas = []
        attempts = 0
        passes = 0
        for index in range(budget):
            setup = pick(index)
            name = setup.name if setup is not None else None
            attempts += 1
            outcome = await self.call_api(messages_for(base, setup))
            if outcome is None:
                # No response at all: the attempt is counted, but there is no
                # metadata to report for it (AMBIGUITIES.md T51).
                continue
            content, meta = outcome
            passed, _extracted, _score, judge_meta = \
                await self.evaluate_response(content, row, row_index)
            if self.is_judge:
                meta["judge_meta"] = judge_meta
            meta["icl_setup"] = name
            meta["evaluation_passed"] = passed
            metas.append(meta)
            if passed:
                passes += 1
            if passed or not gated:
                outputs.append({cfg.output_field: content, "icl_setup": name})
            if gated:
                if passes >= cfg.num_solutions:
                    break
            elif len(outputs) >= cfg.num_solutions:
                break
        collected = len(outputs) if cfg.evaluation is None else passes
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

    # ------------------------------------------------------- agentic ---

    async def run_agentic_loop(self, messages, row, row_index):
        """One agentic loop: request, run tools, repeat until final text."""
        cfg = self.cfg
        conversation = list(messages)
        tools = cfg.tools or None
        metas = []
        tool_calls = []
        content = None
        finish_reason = None
        start = time.monotonic()
        for _ in range(cfg.max_iterations):
            reply = await self.request(conversation, tools=tools)
            if reply is None:
                # The request never produced a response: the loop ends here
                # with no output (AMBIGUITIES.md T71).
                break
            metas.append(reply.meta)
            iteration = len(metas)
            if reply.tool_calls:
                conversation.append(reply.message)
                for call in reply.tool_calls:
                    result = await execute_tool(self.tools, call.name, call.args)
                    tool_calls.append({"iteration": iteration,
                                       "tool": call.name,
                                       "args": call.args,
                                       "result": result})
                    conversation.append({"role": "tool",
                                         "tool_call_id": call.id,
                                         "name": call.name,
                                         "content": result})
                continue
            content = reply.content if isinstance(reply.content, str) else None
            finish_reason = reply.meta.get("finish_reason") or "stop"
            break
        else:
            # Every iteration asked for more tools: the budget is spent.
            finish_reason = "max_iterations"
        latency_ms = int(round((time.monotonic() - start) * 1000))
        return AgenticRun(content, len(metas), tool_calls, metas, latency_ms,
                          finish_reason)

    async def evaluate_agentic(self, run, row, row_index):
        """(passed, extracted, judge_score, judge_meta) for one loop."""
        if run.content is None:
            # No final text to evaluate: a configured evaluation fails.
            passed = None if self.cfg.evaluation is None else False
            return passed, None, None, None
        return await self.evaluate_response(run.content, row, row_index)

    async def run_agentic_row(self, row, messages, row_index):
        """The Part 1 record shape, plus `iterations` and `tool_calls`."""
        run = await self.run_agentic_loop(messages, row, row_index)
        passed, extracted, judge_score, judge_meta = \
            await self.evaluate_agentic(run, row, row_index)
        if run.content is None:
            # A row with no output has failed, as in Part 1.
            passed = False if passed is None else passed
            extracted = None
            judge_score = None
        result = {
            "passed": passed,
            "extracted_answer": extracted,
            "attempts": 1,
            "iterations": run.iterations,
            "tool_calls": run.tool_calls,
        }
        if self.is_judge:
            result["judge_score"] = judge_score
        meta = run.meta
        if meta is not None and self.is_judge:
            meta["judge_meta"] = judge_meta
        output = None if run.content is None else {self.cfg.output_field:
                                                   run.content}
        return {"input": row, "output": output, "result": result, "meta": meta}

    async def run_agentic_multi(self, row, base, row_index):
        """The Part 3 list format: one independent agentic loop per solution."""
        cfg = self.cfg
        icl = cfg.icl
        outputs = []
        metas = []
        attempts = 0
        passes = 0
        for index in range(cfg.num_solutions):
            setup = None if icl is None else icl.select(index)
            name = setup.name if setup is not None else None
            attempts += 1
            run = await self.run_agentic_loop(messages_for(base, setup), row,
                                              row_index)
            passed, _extracted, _score, judge_meta = \
                await self.evaluate_agentic(run, row, row_index)
            meta = run.meta
            if meta is not None:
                if self.is_judge:
                    meta["judge_meta"] = judge_meta
                meta["icl_setup"] = name
                meta["evaluation_passed"] = passed
                meta["iterations"] = run.iterations
                meta["tool_calls"] = run.tool_calls
                metas.append(meta)
            if passed:
                passes += 1
            if run.content is not None:
                outputs.append({cfg.output_field: run.content,
                                "icl_setup": name})
        collected = len(outputs) if cfg.evaluation is None else passes
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

    @property
    def is_judge(self):
        return (self.cfg.evaluation is not None
                and self.cfg.evaluation["type"] == "llm_judge")

    def _record(self, row, content, passed, extracted, attempts, metas,
                judge_score=None):
        if content is None:
            output = None
            extracted = None
            judge_score = None
        else:
            output = {self.cfg.output_field: content}
        if not metas:
            meta = None
        elif len(metas) == 1:
            meta = metas[0]
        else:
            meta = metas
        result = {
            "passed": passed,
            "extracted_answer": extracted,
            "attempts": attempts,
        }
        if self.is_judge:
            result["judge_score"] = judge_score
        return {
            "input": row,
            "output": output,
            "result": result,
            "meta": meta,
        }


async def process(cfg, rows, prepared):
    if not rows:
        return [], Stats()
    stats = Stats()
    concurrency = min(cfg.concurrency, max(1, len(rows)))
    connector = aiohttp.TCPConnector(limit=concurrency,
                                     limit_per_host=concurrency)
    timeout = aiohttp.ClientTimeout(total=None, connect=None,
                                    sock_connect=30, sock_read=None)
    async with aiohttp.ClientSession(connector=connector,
                                     timeout=timeout) as session:
        semaphore = asyncio.Semaphore(concurrency)
        runner = Runner(cfg, session, semaphore, stats)
        tasks = [asyncio.ensure_future(runner.run_row(row, messages, index))
                 for index, (row, messages) in enumerate(zip(rows, prepared))]
        records = await asyncio.gather(*tasks)
    return list(records), stats


async def process_all(jobs):
    """Run every task concurrently; requests may interleave across tasks."""
    results = await asyncio.gather(
        *[process(cfg, rows, prepared) for cfg, rows, prepared in jobs])
    return list(results)


def count_rows(records):
    passed = 0
    failed = 0
    for record in records:
        value = record["result"]["passed"]
        if value is True:
            passed += 1
        elif isinstance(value, int) and not isinstance(value, bool):
            # List format: the row passed when it collected a solution.
            passed += 1 if value > 0 else 0
            failed += 0 if value > 0 else 1
        elif value is None and record["output"] is not None:
            # No evaluation configured: a successful API row counts as passed.
            passed += 1
        else:
            failed += 1
    return passed, failed


def count_solutions(records):
    """How many solutions were written across these rows."""
    total = 0
    for record in records:
        output = record["output"]
        if isinstance(output, list):
            total += len(output)
        elif output is not None:
            total += 1
    return total


def solution_fields(records):
    total_solutions = count_solutions(records)
    average = (round(total_solutions / float(len(records)), 2)
               if records else 0.0)
    return total_solutions, average


def summarise(records, stats):
    passed, failed = count_rows(records)
    total_solutions, average = solution_fields(records)
    elapsed = stats.elapsed
    throughput = (stats.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0
    return {
        "total": len(records),
        "passed": passed,
        "failed": failed,
        "total_solutions": total_solutions,
        "avg_solutions_per_input": average,
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }


def summarise_all(names, results):
    """Aggregate summary plus a per-task block for every task that ran."""
    all_records = []
    for records, _ in results:
        all_records.extend(records)
    combined = Stats.combine([stats for _, stats in results])
    summary = summarise(all_records, combined)
    tasks = {}
    for name, (records, stats) in zip(names, results):
        passed, failed = count_rows(records)
        total_solutions, average = solution_fields(records)
        tasks[name] = {
            "total": len(records),
            "passed": passed,
            "failed": failed,
            "total_solutions": total_solutions,
            "avg_solutions_per_input": average,
            "total_api_calls": stats.api_calls,
        }
    summary["tasks"] = tasks
    return summary


def write_output(path, records):
    try:
        with open(path, "w") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise InputError("could not write output %s: %s" % (path, exc))


# ------------------------------------------------------------------ cli ---

class Parser(argparse.ArgumentParser):
    """argparse exits 2 on usage errors; the spec only defines 0 and 1."""

    def error(self, message):
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(1)


def build_parser():
    parser = Parser(prog="rejector.py", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="run tasks over JSONL input files")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--input", action="append", default=None,
                     help="JSONL input file, or <task>=<path> for multi-task "
                          "configs (repeatable)")
    run.add_argument("--input-dir", dest="input_dir", default=None,
                     help="directory holding <task_name>.jsonl inputs")
    run.add_argument("--output", required=True,
                     help="JSONL output file, or output directory for "
                          "multi-task configs")
    run.add_argument("--task", action="append", dest="task_names", default=None,
                     help="run only the named task (repeatable)")
    run.add_argument("--eval-model", dest="eval_model", default=None,
                     help="override the judge model for llm_judge tasks")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", choices=SCHEMES, default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    run.add_argument("--num-solutions", dest="num_solutions", type=int,
                     default=None,
                     help="number of solutions to collect per input row")
    run.add_argument("--api-type", dest="api_type", choices=API_TYPES,
                     default=None,
                     help="send chat or text-completions requests")
    run.add_argument("--chat-template", dest="chat_template",
                     choices=CHAT_TEMPLATES, default=None,
                     help="template used to render completions prompts")
    run.add_argument("--icl-strategy", dest="icl_strategy",
                     choices=ICL_STRATEGIES, default=None,
                     help="override icl.strategy for every task")
    run.add_argument("--icl-k", dest="icl_k", type=int, default=None,
                     help="override icl.k for every task")
    return parser


def select_tasks(specs, selected):
    """Filter (name, task) specs by the --task flags, preserving order."""
    if not selected:
        return specs
    known = set(name for name, _ in specs)
    for name in selected:
        if name not in known:
            raise ConfigError("config has no task named %r" % name)
    wanted = set(selected)
    return [(name, task) for name, task in specs if name in wanted]


def resolve_inputs(cfgs, multi, args, all_names):
    """Returns a list of input paths aligned with `cfgs`."""
    entries = args.input or []
    if entries and args.input_dir:
        raise ConfigError("--input and --input-dir may not be combined")

    if args.input_dir:
        if not os.path.isdir(args.input_dir):
            raise InputError("input directory not found: %s" % args.input_dir)
        return [os.path.join(args.input_dir, "%s.jsonl" % cfg.name)
                for cfg in cfgs]

    if not entries:
        raise ConfigError("--input or --input-dir is required")

    if multi:
        mapping = {}
        for entry in entries:
            if "=" not in entry:
                raise ConfigError("multi-task configs require --input "
                                  "<task>=<path> (got %r)" % entry)
            name, _, path = entry.partition("=")
            if name not in all_names:
                raise ConfigError("--input names unknown task %r" % name)
            mapping[name] = path
        paths = []
        for cfg in cfgs:
            if cfg.name not in mapping:
                raise InputError("no --input given for task '%s'" % cfg.name)
            paths.append(mapping[cfg.name])
        return paths

    if len(entries) > 1:
        raise ConfigError("--input may only be given once for single-task "
                          "configs")
    entry = entries[0]
    if "=" in entry:
        name, _, path = entry.partition("=")
        if name == cfgs[0].name:
            return [path]
    return [entry]


def resolve_outputs(cfgs, multi, output):
    """Returns a list of output paths aligned with `cfgs`."""
    if not multi:
        return [output]
    if os.path.exists(output) and not os.path.isdir(output):
        raise ConfigError("--output must be a directory for multi-task "
                          "configs: %s" % output)
    try:
        os.makedirs(output, exist_ok=True)
    except OSError as exc:
        raise InputError("could not create output directory %s: %s"
                         % (output, exc))
    return [os.path.join(output, "%s.jsonl" % cfg.name) for cfg in cfgs]


def run_command(args):
    raw = load_config_file(args.config)
    multi, specs = split_config(raw)
    all_names = [name for name, _ in specs]
    selected = select_tasks(specs, args.task_names)
    config_dir = os.path.dirname(os.path.abspath(args.config))
    cfgs = [build_task_config(task, args, name, multi, config_dir)
            for name, task in selected]

    inputs = resolve_inputs(cfgs, multi, args, all_names)
    out_paths = resolve_outputs(cfgs, multi, args.output)

    jobs = []
    for cfg, path in zip(cfgs, inputs):
        rows = load_rows(path)
        jobs.append((cfg, rows, build_messages(cfg, rows)))

    results = asyncio.run(process_all(jobs))
    for path, (records, _) in zip(out_paths, results):
        write_output(path, records)
    summary = summarise_all([cfg.name for cfg in cfgs], results)
    sys.stdout.write(json.dumps(summary) + "\n")
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        sys.stderr.write("error: usage: rejector.py run --config <path> "
                         "--input <path> --output <path>\n")
        return 1
    try:
        return run_command(args)
    except (ConfigError, InputError) as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
