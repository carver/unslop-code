#!/usr/bin/env python3
"""rejector - run YAML-configured generation tasks against an OpenAI-compatible
chat or text completions API and write one JSONL result per input row.

Generation schemes: greedy, sample, rejection and agentic (a tool-calling loop).
With `api_type: completions` the conversation is rendered through a built-in
chat template and posted to `/v1/completions` instead.

Usage:
    python rejector.py run --config <path> --input <path> --output <path>
    python rejector.py run --config <multi> --input <task>=<path> --output <dir>
    python rejector.py run --config <multi> --input-dir <dir> --output <dir>
"""
from __future__ import annotations

import argparse
import asyncio
import copy
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
from dataclasses import dataclass, field
from typing import Any

import yaml

try:
    import aiohttp
except ImportError:  # pragma: no cover - dependency is declared in requirements
    aiohttp = None


EXIT_OK = 0
EXIT_ERROR = 1

SCHEMES = ("greedy", "sample", "rejection", "agentic")
ICL_STRATEGIES = ("fixed", "random", "round_robin")
API_TYPES = ("chat", "completions")
CHAT_TEMPLATES = ("chatml", "llama3", "mistral", "zephyr")
HANDLER_TYPES = ("echo", "static_map", "script")
EVAL_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")

# Evaluation types that compare the response against a row field.
ANSWER_FIELD_TYPES = ("exact_match", "contains")

RESPONSE_PLACEHOLDER = "__response__"
SCRIPT_TIMEOUT_SECONDS = 10.0
TOOL_SCRIPT_TIMEOUT_SECONDS = 10.0   # `script` handlers, unless overridden
DEFAULT_MAX_ITERATIONS = 10          # agentic loop budget (T60)
STATIC_MAP_DEFAULT = "NOT_FOUND"     # `static_map` fallback (spec default)

MAX_REQUESTS_PER_CALL = 3        # 1 initial attempt + 2 retries
RETRY_BACKOFF_SECONDS = 0.05
MAX_IN_FLIGHT = 256

# Part 5: rate limiting, estimation and progress.
RATE_WINDOW_SECONDS = 60.0       # the sliding RPM / TPM window
WORDS_PER_TOKEN = 0.75           # "1 token ~= 0.75 words"
DRY_RUN_TOKEN_FACTOR = 1.33      # dry-run prompt estimate
DEFAULT_CONCURRENCY = 60         # in-flight default when RPM is disabled (T95)
PROGRESS_SECONDS = 5.0           # progress tick
PROGRESS_FRACTION = 0.1          # ... or every 10% of total inputs
PROGRESS_POLL_SECONDS = 0.25
COST_DECIMALS = 6                # "at least four decimal places" (T103)
SCHEMA_KEYWORDS = ("type", "required", "properties", "items", "enum",
                   "minimum", "maximum", "minLength", "maxLength", "pattern")

# `{field}` placeholders; anything else in braces is left alone (AMBIGUITIES T16).
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
# An answer choice is an A-D that is not part of a longer word (T21).
LETTER_RE = re.compile(r"(?<![A-Za-z])([A-D])(?![A-Za-z])")
# Completions-mode tool calls: <tool_call>{...}</tool_call> blocks.
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
                          re.DOTALL)


class UserError(Exception):
    """A configuration or input error: reported on stderr, exit code 1."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class Evaluation:
    type: str
    answer_field: str | None = None
    extract: str = "full"
    pattern: str | None = None
    # `script`
    command_template: str | None = None
    success_exit_code: int = 0
    # `llm_judge`
    judge_system: str | None = None
    judge_user: str | None = None
    threshold: float | None = None
    model: str | None = None


@dataclass
class IclExample:
    """One in-context example: a row-shaped input and a verbatim reply."""
    input: dict
    output: str


@dataclass
class IclSetup:
    name: str
    examples: list[IclExample]


@dataclass
class IclConfig:
    setups: list[IclSetup]
    strategy: str = "fixed"
    k: int | None = None            # None means "all examples" (spec default)

    def shots(self, setup: IclSetup) -> list[IclExample]:
        """The examples to insert for `setup`: the first `k` of them (T43)."""
        if self.k is None:
            return setup.examples
        return setup.examples[:max(0, self.k)]


@dataclass
class RateLimits:
    """The `rate_limits` block: `None` means "not configured" (T94)."""
    rpm: int | None = None
    tpm: int | None = None
    max_concurrent: int = DEFAULT_CONCURRENCY


@dataclass
class CostConfig:
    """The `cost` block.  `configured` drives the summary's `cost` field."""
    prompt_per_1k: float = 0.0
    completion_per_1k: float = 0.0
    budget: float | None = None
    configured: bool = False


@dataclass
class TaskConfig:
    name: str
    api_url: str
    model: str
    rpm: int | None
    system_template: str | None
    user_template: str
    scheme: str
    temperature: float
    max_tokens: int
    n: int
    evaluation: Evaluation | None
    output_field: str
    icl: IclConfig | None = None
    num_solutions: int = 1
    max_attempts: int | None = None
    api_type: str = "chat"
    chat_template: str = "chatml"
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    tools: list["ToolSpec"] = field(default_factory=list)
    tpm: int | None = None
    max_concurrent: int = DEFAULT_CONCURRENCY
    cost: CostConfig = field(default_factory=CostConfig)
    output_schema: dict | None = None

    @property
    def uses_list_format(self) -> bool:
        """Part 3 rows: a list of solutions, list `meta`, counting `result`."""
        return self.icl is not None or self.num_solutions > 1

    @property
    def is_agentic(self) -> bool:
        return self.scheme == "agentic"

    @property
    def active_tools(self) -> list["ToolSpec"]:
        """Tools only mean something to the agentic loop (AMBIGUITIES T69)."""
        return self.tools if self.is_agentic else []

    @property
    def tool_map(self) -> dict[str, "ToolSpec"]:
        return {tool.name: tool for tool in self.tools}

    @property
    def endpoint(self) -> str:
        base = self.api_url.rstrip("/")
        if self.api_type == "completions":
            return base + "/v1/completions"
        return base + "/v1/chat/completions"

    @property
    def concurrency(self) -> int:
        """The hard in-flight cap: `max_concurrent` (T95)."""
        return max(1, min(int(self.max_concurrent), MAX_IN_FLIGHT))

    @property
    def avg_attempts(self) -> int:
        """Dry-run attempts per input: `n` for rejection, else 1."""
        return self.n if self.scheme == "rejection" else 1


def _as_mapping(value: Any, label: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise UserError(f"config: '{label}' must be a mapping")
    return value


def _as_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UserError(f"config: '{label}' must be a number")
    return float(value)


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise UserError(f"config: '{label}' must be an integer")
    return int(value)


def load_config_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except FileNotFoundError:
        raise UserError(f"config file not found: {path}")
    except OSError as exc:
        raise UserError(f"could not read config file {path}: {exc}")
    except yaml.YAMLError as exc:
        raise UserError(f"could not parse YAML config {path}: {exc}")
    if raw is None:
        raise UserError(f"config file is empty: {path}")
    if not isinstance(raw, dict):
        raise UserError("config: top level must be a mapping with a 'task' key")
    return raw


def deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge `override` onto `base` (T20); scalars replace."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged.get(key), value) if key in merged \
                else value
        return merged
    return override


def load_task_definitions(raw: dict) -> tuple[dict[str, dict], bool]:
    """Return ({name: task mapping}, is_multi_task).

    A top-level `task` key always means the Part 1 single-task format (T41).
    """
    if "task" in raw:
        task = _as_mapping(raw["task"], "task")
        name = task.get("name", "task")
        if not isinstance(name, str) or not name:
            raise UserError("config: 'task.name' must be a non-empty string")
        return {name: task}, False

    if "tasks" not in raw:
        raise UserError("config: missing required 'task' section")

    tasks = _as_mapping(raw["tasks"], "tasks")
    if not tasks:
        raise UserError("config: 'tasks' must contain at least one task")
    defaults = _as_mapping(raw.get("defaults"), "defaults")

    resolved: dict[str, dict] = {}
    for name, task in tasks.items():
        if not isinstance(name, str) or not name:
            raise UserError("config: task names must be non-empty strings")
        merged = deep_merge(copy.deepcopy(defaults),
                            _as_mapping(task, f"tasks.{name}"))
        resolved[str(name)] = merged
    return resolved, True


def build_task_config(name: str, task: dict, args: argparse.Namespace,
                      label: str, config_dir: str = "") -> TaskConfig:
    """Merge one task mapping with CLI overrides and validate the result."""
    api_url = args.api_url if args.api_url is not None else task.get("api_url")
    if not api_url or not isinstance(api_url, str):
        raise UserError(f"config: '{label}.api_url' is required")

    model = args.model if args.model is not None else task.get("model")
    if not model or not isinstance(model, str):
        raise UserError(f"config: '{label}.model' is required")

    limits = build_rate_limits(task, args, label)
    rpm = limits.rpm

    if "prompt" not in task or task.get("prompt") is None:
        raise UserError(f"config: missing required '{label}.prompt' section")
    prompt = _as_mapping(task["prompt"], f"{label}.prompt")
    user_template = prompt.get("user")
    if not isinstance(user_template, str) or not user_template:
        raise UserError(f"config: '{label}.prompt.user' is required")
    system_template = prompt.get("system")
    if system_template is not None and not isinstance(system_template, str):
        raise UserError(f"config: '{label}.prompt.system' must be a string")

    generation = _as_mapping(task.get("generation"), f"{label}.generation")

    scheme = args.scheme if args.scheme is not None else generation.get("scheme",
                                                                        "greedy")
    if scheme not in SCHEMES:
        raise UserError(
            f"config: unknown generation scheme {scheme!r}; "
            f"expected one of {', '.join(SCHEMES)}")

    if args.temperature is not None:
        temperature = float(args.temperature)
    else:
        temperature = _as_number(generation.get("temperature", 0.0),
                                 f"{label}.generation.temperature")

    max_tokens = (args.max_tokens if args.max_tokens is not None
                  else generation.get("max_tokens", 512))
    max_tokens = _as_int(max_tokens, f"{label}.generation.max_tokens")
    if max_tokens < 1:
        raise UserError(f"config: '{label}.generation.max_tokens' must be >= 1")

    n = args.n if args.n is not None else generation.get("n", 1)
    n = _as_int(n, f"{label}.generation.n")
    if n < 1:
        raise UserError(f"config: '{label}.generation.n' must be >= 1")

    # The agentic loop budget; `10` when unset (AMBIGUITIES T60, T61).
    max_iterations = generation.get("max_iterations", DEFAULT_MAX_ITERATIONS)
    max_iterations = _as_int(max_iterations,
                             f"{label}.generation.max_iterations")
    if max_iterations < 1:
        raise UserError(
            f"config: '{label}.generation.max_iterations' must be >= 1")

    api_type = (args.api_type if args.api_type is not None
                else task.get("api_type", "chat"))
    if api_type not in API_TYPES:
        raise UserError(
            f"config: unknown api_type {api_type!r}; "
            f"expected one of {', '.join(API_TYPES)}")

    chat_template = (args.chat_template if args.chat_template is not None
                     else task.get("chat_template", "chatml"))
    if chat_template not in CHAT_TEMPLATES:
        raise UserError(
            f"config: unknown chat_template {chat_template!r}; "
            f"expected one of {', '.join(CHAT_TEMPLATES)}")

    tools = build_tools(task.get("tools"), label)

    if scheme == "greedy":
        # greedy forces temperature to 0.0 (AMBIGUITIES T18).
        temperature = 0.0
    elif scheme == "agentic":
        # `agentic` is a control-flow mode, not a sampling policy: the
        # configured temperature is used as-is, including the `0.0` of the
        # spec's own example (AMBIGUITIES T63).
        pass
    elif temperature <= 0:
        raise UserError(
            f"config: scheme {scheme!r} requires 'temperature' > 0 "
            f"(got {temperature})")

    evaluation = build_evaluation(task.get("evaluation"), label,
                                  args.eval_model)
    output_schema = build_output_schema(task.get("output_schema"), label)
    # Rejection needs something to reject with: an evaluation block, or an
    # `output_schema` on its own (part 5).
    if scheme == "rejection" and evaluation is None and output_schema is None:
        raise UserError(f"config: '{label}.evaluation' is required for "
                        "scheme 'rejection'")
    if evaluation is not None and evaluation.type == "llm_judge" \
            and evaluation.model is None:
        evaluation.model = model

    output_field = task.get("output_field", "output")
    if not isinstance(output_field, str) or not output_field:
        raise UserError(f"config: '{label}.output_field' must be a non-empty string")

    num_solutions = (args.num_solutions if args.num_solutions is not None
                     else task.get("num_solutions", 1))
    num_solutions = _as_int(num_solutions, f"{label}.num_solutions")
    if num_solutions < 1:
        raise UserError(f"config: '{label}.num_solutions' must be >= 1")

    max_attempts = generation.get("max_attempts")
    if max_attempts is None:
        # Rejection's attempt budget when unset (the other schemes have an
        # exact attempt count of their own, T59).
        max_attempts = 3 * num_solutions
    else:
        max_attempts = _as_int(max_attempts, f"{label}.generation.max_attempts")
        if max_attempts < 1:
            raise UserError(
                f"config: '{label}.generation.max_attempts' must be >= 1")

    icl = build_icl_config(task.get("icl"), label, config_dir, user_template,
                           args)

    return TaskConfig(
        name=name,
        api_url=api_url,
        model=model,
        rpm=rpm,
        system_template=system_template,
        user_template=user_template,
        scheme=scheme,
        temperature=temperature,
        max_tokens=max_tokens,
        n=n,
        evaluation=evaluation,
        output_field=output_field,
        icl=icl,
        num_solutions=num_solutions,
        max_attempts=max_attempts,
        api_type=api_type,
        chat_template=chat_template,
        max_iterations=max_iterations,
        tools=tools,
        tpm=limits.tpm,
        max_concurrent=limits.max_concurrent,
        cost=build_cost_config(task.get("cost"), args, label),
        output_schema=output_schema,
    )


def build_rate_limits(task: dict, args: argparse.Namespace,
                      label: str) -> RateLimits:
    """Parse `rate_limits`, the legacy top-level `rpm` and the CLI flags.

    `rate_limits.rpm` is the new home of the old `rpm` key; when neither is
    given, RPM limiting is disabled for the task (T94).
    """
    raw = _as_mapping(task.get("rate_limits"), f"{label}.rate_limits")

    def pick(flag: Any, key: str, fallback: Any = None) -> Any:
        if flag is not None:
            return flag
        if key in raw and raw[key] is not None:
            return raw[key]
        return fallback

    rpm = pick(getattr(args, "rpm", None), "rpm", task.get("rpm"))
    if rpm is not None:
        rpm = _as_int(rpm, f"{label}.rate_limits.rpm")
        if rpm < 1:
            raise UserError(f"config: '{label}.rpm' must be >= 1")

    tpm = pick(getattr(args, "tpm", None), "tpm")
    if tpm is not None:
        tpm = _as_int(tpm, f"{label}.rate_limits.tpm")
        if tpm < 1:
            raise UserError(f"config: '{label}.rate_limits.tpm' must be >= 1")

    max_concurrent = pick(getattr(args, "max_concurrent", None),
                          "max_concurrent")
    if max_concurrent is None:
        # Keep part 1's pipeline sizing: roughly `rpm` requests in flight
        # (AMBIGUITIES T95).
        base = rpm if rpm is not None else DEFAULT_CONCURRENCY
        max_concurrent = max(1, min(int(base), MAX_IN_FLIGHT))
    else:
        max_concurrent = _as_int(max_concurrent,
                                 f"{label}.rate_limits.max_concurrent")
        if max_concurrent < 1:
            raise UserError(
                f"config: '{label}.rate_limits.max_concurrent' must be >= 1")

    return RateLimits(rpm=rpm, tpm=tpm, max_concurrent=max_concurrent)


def build_cost_config(raw: Any, args: argparse.Namespace,
                      label: str) -> CostConfig:
    """Parse the `cost` block and `--budget`."""
    budget_flag = getattr(args, "budget", None)
    if raw is None and budget_flag is None:
        return CostConfig()
    section = _as_mapping(raw, f"{label}.cost")

    def rate(key: str) -> float:
        value = section.get(key)
        if value is None:
            return 0.0
        value = _as_number(value, f"{label}.cost.{key}")
        if value < 0:
            raise UserError(f"config: '{label}.cost.{key}' must be >= 0")
        return value

    budget = budget_flag if budget_flag is not None else section.get("budget")
    if budget is not None:
        budget = _as_number(budget, f"{label}.cost.budget")
        if budget < 0:
            raise UserError(f"config: '{label}.cost.budget' must be >= 0")

    return CostConfig(prompt_per_1k=rate("prompt_cost_per_1k"),
                      completion_per_1k=rate("completion_cost_per_1k"),
                      budget=budget, configured=True)


def build_output_schema(raw: Any, label: str) -> dict | None:
    """Validate the shape of an `output_schema` block."""
    if raw is None:
        return None
    schema = _as_mapping(raw, f"{label}.output_schema")
    if not schema:
        raise UserError(f"config: '{label}.output_schema' must not be empty")
    return schema


# ---------------------------------------------------------------------------
# In-context learning setups
# ---------------------------------------------------------------------------
ICL_RECORD_SHAPE = 'expected {"input": <object>, "output": <string>}'


def build_icl_config(raw: Any, label: str, config_dir: str,
                     user_template: str,
                     args: argparse.Namespace) -> IclConfig | None:
    """Parse a task's `icl` section, loading any file-backed setups.

    Returns `None` when the task configures no usable setup (T55).
    """
    strategy_flag = getattr(args, "icl_strategy", None)
    k_flag = getattr(args, "icl_k", None)

    section = _as_mapping(raw, f"{label}.icl") if raw is not None else {}
    raw_setups = section.get("setups")
    if raw_setups is None:
        return None
    if not isinstance(raw_setups, list):
        raise UserError(f"config: '{label}.icl.setups' must be a list")

    setups = [build_icl_setup(entry, label, index, config_dir)
              for index, entry in enumerate(raw_setups)]
    if not setups:
        return None

    strategy = (strategy_flag if strategy_flag is not None
                else section.get("strategy", "fixed"))
    if strategy not in ICL_STRATEGIES:
        raise UserError(
            f"config: unknown icl strategy {strategy!r}; "
            f"expected one of {', '.join(ICL_STRATEGIES)}")

    k = k_flag if k_flag is not None else section.get("k")
    if k is not None:
        k = _as_int(k, f"{label}.icl.k")
        if k < 0:
            raise UserError(f"config: '{label}.icl.k' must be >= 0")

    # Every example is rendered with `prompt.user`, so it must carry the
    # fields that template references - check before any request goes out (T53).
    fields = [f for f in template_fields(user_template)
              if f != RESPONSE_PLACEHOLDER]
    for setup in setups:
        for index, example in enumerate(setup.examples):
            for field_name in fields:
                if field_name not in example.input:
                    raise UserError(
                        f"config: icl setup {setup.name!r} example {index}: "
                        f"missing field {field_name!r} referenced by the "
                        f"prompt template")

    return IclConfig(setups=setups, strategy=strategy, k=k)


def build_icl_setup(entry: Any, label: str, index: int,
                    config_dir: str) -> IclSetup:
    setup = _as_mapping(entry, f"{label}.icl.setups[{index}]")
    name = setup.get("name")
    if not isinstance(name, str) or not name:
        raise UserError(
            f"config: '{label}.icl.setups[{index}].name' is required")

    has_examples = setup.get("examples") is not None
    has_file = setup.get("file") is not None
    if has_examples == has_file:
        raise UserError(
            f"config: icl setup {name!r} needs exactly one of 'examples' or "
            f"'file'")

    if has_file:
        path = setup["file"]
        if not isinstance(path, str) or not path:
            raise UserError(
                f"config: icl setup {name!r}: 'file' must be a path string")
        # Relative to the config file's directory, not the process cwd.
        if not os.path.isabs(path):
            path = os.path.join(config_dir, path)
        return IclSetup(name=name, examples=load_icl_file(path, name))

    raw_examples = setup["examples"]
    if not isinstance(raw_examples, list):
        raise UserError(
            f"config: icl setup {name!r}: 'examples' must be a list")
    examples = [
        parse_icl_record(record,
                         f"config: icl setup {name!r} example {position}",
                         json_wording=False)
        for position, record in enumerate(raw_examples)]
    return IclSetup(name=name, examples=examples)


def load_icl_file(path: str, setup_name: str) -> list[IclExample]:
    """Read a JSONL example file; any bad line terminates the run (exit 1)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise UserError(f"icl setup {setup_name!r}: file not found: {path}")
    except OSError as exc:
        raise UserError(
            f"icl setup {setup_name!r}: could not read {path}: {exc}")

    examples: list[IclExample] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue                      # "each non-empty line"
        where = f"icl setup {setup_name!r}: {path} line {lineno}"
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UserError(f"{where}: not valid JSON: {exc}")
        examples.append(parse_icl_record(record, where))
    return examples


def parse_icl_record(record: Any, where: str,
                     json_wording: bool = True) -> IclExample:
    """Validate one `{"input": <object>, "output": <string>}` record (T52)."""
    message = (f"{where}: not valid JSON example: {ICL_RECORD_SHAPE}"
               if json_wording else f"{where}: {ICL_RECORD_SHAPE}")
    if not isinstance(record, dict):
        raise UserError(message)
    if "input" not in record or "output" not in record:
        raise UserError(message)
    if not isinstance(record["input"], dict) \
            or not isinstance(record["output"], str):
        raise UserError(message)
    return IclExample(input=record["input"], output=record["output"])


def build_evaluation(raw: Any, label: str = "task",
                     eval_model: str | None = None) -> Evaluation | None:
    if raw is None:
        return None
    section = _as_mapping(raw, f"{label}.evaluation")
    if not section:
        return None
    etype = section.get("type")
    if etype not in EVAL_TYPES:
        raise UserError(
            f"config: unknown evaluation type {etype!r}; "
            f"expected one of {', '.join(EVAL_TYPES)}")

    extract = section.get("extract", "full")
    if extract is None:
        extract = "full"
    if extract not in EXTRACT_METHODS:
        raise UserError(
            f"config: unknown extract method {extract!r}; "
            f"expected one of {', '.join(EXTRACT_METHODS)}")

    answer_field = section.get("answer_field")
    pattern = section.get("pattern")

    if etype in ANSWER_FIELD_TYPES:
        if not answer_field or not isinstance(answer_field, str):
            raise UserError(
                f"config: evaluation type {etype!r} requires 'answer_field'")
    if etype == "regex":
        if not pattern or not isinstance(pattern, str):
            raise UserError("config: evaluation type 'regex' requires 'pattern'")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise UserError(f"config: invalid regex 'pattern': {exc}")

    evaluation = Evaluation(type=etype, answer_field=answer_field,
                            extract=extract, pattern=pattern)

    if etype == "script":
        command_template = section.get("command_template")
        if not command_template or not isinstance(command_template, str):
            raise UserError("config: evaluation type 'script' requires "
                            "'command_template'")
        evaluation.command_template = command_template
        evaluation.success_exit_code = _as_int(
            section.get("success_exit_code", 0),
            f"{label}.evaluation.success_exit_code")

    if etype == "llm_judge":
        judge = section.get("judge_prompt")
        if judge is None:
            raise UserError("config: evaluation type 'llm_judge' requires "
                            "'judge_prompt'")
        judge = _as_mapping(judge, f"{label}.evaluation.judge_prompt")
        judge_user = judge.get("user")
        if not isinstance(judge_user, str) or not judge_user:
            raise UserError(f"config: '{label}.evaluation.judge_prompt.user' "
                            "is required")
        judge_system = judge.get("system")
        if judge_system is not None and not isinstance(judge_system, str):
            raise UserError(f"config: '{label}.evaluation.judge_prompt.system' "
                            "must be a string")
        if "threshold" not in section or section.get("threshold") is None:
            raise UserError("config: evaluation type 'llm_judge' requires "
                            "'threshold'")
        evaluation.judge_system = judge_system
        evaluation.judge_user = judge_user
        evaluation.threshold = _as_number(section["threshold"],
                                          f"{label}.evaluation.threshold")
        # `--eval-model` beats `evaluation.model`, which beats the task model
        # (T35); the task model is filled in by the caller.
        model = eval_model if eval_model is not None else section.get("model")
        if model is not None and (not isinstance(model, str) or not model):
            raise UserError(f"config: '{label}.evaluation.model' must be a "
                            "non-empty string")
        evaluation.model = model

    return evaluation


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
def load_rows(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise UserError(f"input file not found: {path}")
    except OSError as exc:
        raise UserError(f"could not read input file {path}: {exc}")

    rows: list[dict] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UserError(f"input line {lineno}: invalid JSON: {exc}")
        if not isinstance(row, dict):
            raise UserError(f"input line {lineno}: expected a JSON object")
        rows.append(row)
    return rows


def template_fields(template: str | None) -> list[str]:
    if not template:
        return []
    seen: list[str] = []
    for name in PLACEHOLDER_RE.findall(template):
        if name not in seen:
            seen.append(name)
    return seen


def render_template(template: str, row: dict) -> str:
    return PLACEHOLDER_RE.sub(lambda m: str(row[m.group(1)]), template)


def required_fields(cfg: TaskConfig) -> list[str]:
    """Row fields every input row must carry for this task (T39).

    `__response__` is supplied at runtime and is never a row field.
    """
    required: list[str] = []
    templates = [cfg.system_template, cfg.user_template]
    evaluation = cfg.evaluation
    if evaluation is not None:
        templates += [evaluation.judge_system, evaluation.judge_user,
                      evaluation.command_template]
    for template in templates:
        for name in template_fields(template):
            if name != RESPONSE_PLACEHOLDER and name not in required:
                required.append(name)
    return required


def validate_rows(cfg: TaskConfig, rows: list[dict]) -> None:
    """Fail before any request is issued (AMBIGUITIES T8)."""
    required = required_fields(cfg)

    evaluation = cfg.evaluation
    answer_field = (evaluation.answer_field
                    if evaluation and evaluation.type in ANSWER_FIELD_TYPES
                    else None)

    for index, row in enumerate(rows):
        for name in required:
            if name not in row:
                raise UserError(
                    f"input row {index}: missing field {name!r} referenced by "
                    f"the prompt template")
        if answer_field and answer_field not in row:
            raise UserError(
                f"input row {index}: missing field {answer_field!r} required by "
                f"the configured evaluation")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def extract_answer(text: str, method: str) -> str | None:
    if text is None:
        return None
    if method == "full":
        return text.strip()
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return None
    if method == "last_number":
        matches = NUMBER_RE.findall(text)
        return matches[-1] if matches else None
    if method == "first_number":
        match = NUMBER_RE.search(text)
        return match.group(0) if match else None
    if method == "letter":
        match = LETTER_RE.search(text)
        return match.group(1) if match else None
    raise UserError(f"unknown extract method {method!r}")


@dataclass
class Verdict:
    """The outcome of evaluating one generated response."""
    passed: bool
    extracted: str | None = None
    judge_score: float | None = None
    judge_meta: dict | None = None


def evaluate(cfg: TaskConfig, row: dict, text: str) -> tuple[bool, str | None]:
    """Return (passed, extracted_answer) for a response body."""
    evaluation = cfg.evaluation
    assert evaluation is not None
    extracted = extract_answer(text, evaluation.extract)

    if evaluation.type == "exact_match":
        expected = str(row.get(evaluation.answer_field, "")).strip()
        passed = extracted is not None and extracted.strip() == expected
    elif evaluation.type == "contains":
        expected = str(row.get(evaluation.answer_field, ""))
        passed = expected in text
    elif evaluation.type == "regex":
        passed = re.search(evaluation.pattern, text) is not None
    else:  # pragma: no cover - validated at config load
        raise UserError(f"unknown evaluation type {evaluation.type!r}")

    return passed, extracted


def render_command(evaluation: Evaluation, row: dict, text: str) -> str:
    """Render `command_template` against the row, then resolve `__response__`.

    Row fields are expanded first; a `{__response__}` that only appears *after*
    that expansion (because it lived inside a row field) is substituted in a
    second pass.  Substitution is textual, never shell-quoted (T28).
    """
    context = dict(row)
    context[RESPONSE_PLACEHOLDER] = text
    command = render_template(evaluation.command_template, context)
    if "{" + RESPONSE_PLACEHOLDER + "}" in command:
        command = command.replace("{" + RESPONSE_PLACEHOLDER + "}", text)
    return command


async def run_script_evaluation(evaluation: Evaluation, row: dict,
                                text: str) -> Verdict:
    """Run the rendered command in a shell; its exit code is the verdict."""
    command = render_command(evaluation, row, text)
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Own process group, so a timeout can take down the shell's
            # children too - otherwise a survivor keeps the pipes open.
            start_new_session=True)
    except OSError:
        return Verdict(passed=False)

    try:
        # stdout/stderr are captured and drained, then discarded: the spec
        # forbids putting them in the JSONL output.
        await asyncio.wait_for(process.communicate(),
                               timeout=SCRIPT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        # A timeout is simply a failed evaluation.
        _kill_process_group(process)
        try:
            await process.wait()
        except Exception:  # pragma: no cover - best-effort reaping
            pass
        return Verdict(passed=False)

    return Verdict(passed=process.returncode == evaluation.success_exit_code)


def _kill_process_group(process) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except (ProcessLookupError, OSError):
            pass


def parse_score(extracted: str | None) -> float | None:
    """Turn an extracted judge answer into a number (T25)."""
    if extracted is None:
        return None
    try:
        score = float(extracted)
    except ValueError:
        return None
    return int(score) if score.is_integer() else score


# ---------------------------------------------------------------------------
# Tools (agentic generation)
# ---------------------------------------------------------------------------
@dataclass
class ToolSpec:
    """One declared tool: what the model is told, and what runs locally."""
    name: str
    description: str
    parameters: dict
    handler: str
    mapping: dict = field(default_factory=dict)
    default: str = STATIC_MAP_DEFAULT
    command: str | None = None
    arg_field: str | None = None
    timeout: float = TOOL_SCRIPT_TIMEOUT_SECONDS

    @property
    def definition(self) -> dict:
        """The OpenAI `tools` entry; the handler stays local (T79)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def build_tools(raw: Any, label: str) -> list[ToolSpec]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise UserError(f"config: '{label}.tools' must be a list")

    tools: list[ToolSpec] = []
    for index, entry in enumerate(raw):
        where = f"{label}.tools[{index}]"
        entry = _as_mapping(entry, where)

        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise UserError(f"config: '{where}.name' is required")

        description = entry.get("description", "")
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise UserError(f"config: '{where}.description' must be a string")

        parameters = entry.get("parameters")
        if parameters is None:
            parameters = {"type": "object", "properties": {}}
        if not isinstance(parameters, dict):
            raise UserError(f"config: '{where}.parameters' must be a mapping")

        handler = _as_mapping(entry.get("handler"), f"{where}.handler")
        htype = handler.get("type")
        if htype not in HANDLER_TYPES:
            raise UserError(
                f"config: '{where}.handler.type' is {htype!r}; expected one "
                f"of {', '.join(HANDLER_TYPES)}")

        tool = ToolSpec(name=name, description=description,
                        parameters=parameters, handler=htype)

        if htype == "static_map":
            tool.mapping = _as_mapping(handler.get("mapping"),
                                       f"{where}.handler.mapping")
            default = handler.get("default", STATIC_MAP_DEFAULT)
            tool.default = STATIC_MAP_DEFAULT if default is None else str(default)

        if htype == "script":
            command = handler.get("command")
            if not isinstance(command, str) or not command.strip():
                raise UserError(
                    f"config: '{where}.handler.command' is required")
            arg_field = handler.get("arg_field")
            if not isinstance(arg_field, str) or not arg_field:
                raise UserError(
                    f"config: '{where}.handler.arg_field' is required")
            tool.command = command
            tool.arg_field = arg_field
            if handler.get("timeout") is not None:
                timeout = _as_number(handler["timeout"],
                                     f"{where}.handler.timeout")
                if timeout <= 0:
                    raise UserError(
                        f"config: '{where}.handler.timeout' must be > 0")
                tool.timeout = timeout

        tools.append(tool)
    return tools


@dataclass
class ToolCall:
    """One tool call requested by the model, with its arguments parsed."""
    name: str
    args: dict
    id: str | None = None
    error: str | None = None


def parse_tool_arguments(raw: Any) -> tuple[dict, str | None]:
    """`function.arguments` -> (parsed object, error string) (T74)."""
    if raw is None:
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}, "ERROR: could not parse tool arguments as JSON"
        if isinstance(parsed, dict):
            return parsed, None
    return {}, "ERROR: tool arguments must be a JSON object"


def parse_message_tool_calls(message: Any) -> list[ToolCall]:
    """Tool calls from a chat `message` object (the normal OpenAI shape)."""
    if not isinstance(message, dict):
        return []
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    calls: list[ToolCall] = []
    for raw in raw_calls:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") or {}
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        args, error = parse_tool_arguments(function.get("arguments"))
        calls.append(ToolCall(name=name, args=args, id=raw.get("id"),
                              error=error))
    return calls


def parse_text_tool_calls(text: str | None) -> list[ToolCall]:
    """Tool calls from `<tool_call>{...}</tool_call>` blocks (T86)."""
    calls: list[ToolCall] = []
    for match in TOOL_CALL_RE.finditer(text or ""):
        try:
            payload = json.loads(match.group(1))
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            continue
        args, error = parse_tool_arguments(payload.get("arguments"))
        calls.append(ToolCall(name=name, args=args, error=error))
    return calls


def static_map_key(tool: ToolSpec, args: dict) -> str | None:
    """The value looked up in `mapping`: the first required parameter (T75)."""
    candidates: list[str] = []
    required = tool.parameters.get("required")
    if isinstance(required, list):
        candidates += [name for name in required if isinstance(name, str)]
    properties = tool.parameters.get("properties")
    if isinstance(properties, dict):
        candidates += [name for name in properties if isinstance(name, str)]
    for name in candidates:
        if name in args:
            return str(args[name])
    for value in args.values():           # last resort: whatever was sent
        return str(value)
    return None


async def execute_tool_call(cfg: TaskConfig, call: ToolCall) -> str:
    """Run one tool call's handler and return its result string."""
    if call.error is not None:
        return call.error
    tool = cfg.tool_map.get(call.name)
    if tool is None:
        return f"ERROR: unknown tool {call.name!r}"

    if tool.handler == "echo":
        return json.dumps(call.args)

    if tool.handler == "static_map":
        key = static_map_key(tool, call.args)
        if key is None:
            return tool.default
        value = tool.mapping.get(key, tool.default)
        return str(value)

    return await run_tool_script(tool, call.args)


async def run_tool_script(tool: ToolSpec, args: dict) -> str:
    """`script` handler: `command` plus one argument, no shell (T77, T78)."""
    value = args.get(tool.arg_field, "")
    if not isinstance(value, str):
        value = json.dumps(value) if isinstance(value, (dict, list)) \
            else str(value)
    argv = shlex.split(tool.command) + [value]

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Own process group so a timeout takes the whole tree down.
            start_new_session=True)
    except (OSError, ValueError) as exc:
        return f"ERROR: {exc}"

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(),
                                                timeout=tool.timeout)
    except asyncio.TimeoutError:
        _kill_process_group(process)
        try:
            await process.wait()
        except Exception:  # pragma: no cover - best-effort reaping
            pass
        return f"ERROR: timeout after {tool.timeout:g}s"

    if process.returncode != 0:
        message = stderr.decode("utf-8", "replace").strip()
        if not message:
            message = f"command exited with status {process.returncode}"
        return f"ERROR: {message}"
    return stdout.decode("utf-8", "replace").strip()


# ---------------------------------------------------------------------------
# Chat templates (completions mode)
# ---------------------------------------------------------------------------
def message_text(message: dict) -> str:
    content = message.get("content")
    return "" if content is None else str(content)


def render_prompt(messages: list[dict], template: str) -> str:
    """Render a conversation into a prompt string (T81, T82, T83, T84)."""
    if template == "chatml":
        blocks = [f"<|im_start|>{m['role']}\n{message_text(m)}<|im_end|>\n"
                  for m in messages]
        return "".join(blocks) + "<|im_start|>assistant\n"

    if template == "zephyr":
        blocks = [f"<|{m['role']}|>\n{message_text(m)}</s>\n"
                  for m in messages]
        return "".join(blocks) + "<|assistant|>\n"

    if template == "llama3":
        blocks = ["<|begin_of_text|>"]
        for message in messages:
            blocks.append(
                f"<|start_header_id|>{message['role']}<|end_header_id|>\n\n"
                f"{message_text(message)}<|eot_id|>")
        return "".join(blocks) + \
            "<|start_header_id|>assistant<|end_header_id|>\n\n"

    if template == "mistral":
        # Mistral has no system marker: the system text rides along with the
        # first instruction block, and every later turn repeats [INST] (T83).
        blocks: list[str] = []
        pending: str | None = None
        for message in messages:
            role = message["role"]
            content = message_text(message)
            if role == "system":
                pending = content if pending is None else f"{pending}\n\n{content}"
                continue
            if role == "assistant":
                blocks.append(f" {content}</s>")
                continue
            if pending is not None:
                content = f"{pending}\n\n{content}"
                pending = None
            blocks.append(f"[INST] {content} [/INST]")
        if pending is not None:
            blocks.append(f"[INST] {pending} [/INST]")
        return "".join(blocks)

    raise UserError(f"unknown chat template {template!r}")


TOOL_PROMPT_HEADER = "You have access to the following tools:"
TOOL_PROMPT_FOOTER = (
    "To call a tool, reply with one block per call of the form:\n"
    "<tool_call>\n"
    "{\"name\": <tool name>, \"arguments\": <arguments object>}\n"
    "</tool_call>\n"
    "When you have the final answer, reply with plain text and no tool call "
    "blocks.")


def render_tool_preamble(tools: list[ToolSpec]) -> str:
    """The tool definitions, rendered for a completions prompt (T85)."""
    lines = [TOOL_PROMPT_HEADER, ""]
    for tool in tools:
        lines.append(json.dumps({"name": tool.name,
                                 "description": tool.description,
                                 "parameters": tool.parameters}))
    lines += ["", TOOL_PROMPT_FOOTER]
    return "\n".join(lines)


def with_tool_preamble(messages: list[dict],
                       tools: list[ToolSpec]) -> list[dict]:
    """Fold the tool definitions into the system message (T85)."""
    if not tools:
        return messages
    preamble = render_tool_preamble(tools)
    rendered = [dict(message) for message in messages]
    for message in rendered:
        if message.get("role") == "system":
            message["content"] = f"{message_text(message)}\n\n{preamble}"
            return rendered
    return [{"role": "system", "content": preamble}] + rendered


# ---------------------------------------------------------------------------
# Structured output validation (JSON Schema draft 7 subset)
# ---------------------------------------------------------------------------
@dataclass
class SchemaResult:
    """The outcome of validating one response against `output_schema`."""
    valid: bool
    value: Any = None
    error: str | None = None


def json_type_name(value: Any) -> str:
    """The draft-7 type name of a decoded JSON value."""
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
    return "unknown"


def json_type_matches(value: Any, expected: str) -> bool:
    actual = json_type_name(value)
    if expected == "number":
        # draft 7: every integer is a number.
        return actual in ("number", "integer")
    if expected == "integer":
        # draft 7: 5.0 is an integer.
        return actual == "integer" or (actual == "number"
                                       and float(value).is_integer())
    return actual == expected


def _where(path: str) -> str:
    return path if path else "output"


def validate_json_schema(value: Any, schema: Any,
                         path: str = "") -> str | None:
    """Validate `value`; return a human-readable message, or None if valid."""
    if isinstance(schema, bool):
        return None if schema else f"{_where(path)}: schema rejects all values"
    if not isinstance(schema, dict):
        return None

    expected = schema.get("type")
    if expected is not None:
        options = expected if isinstance(expected, list) else [expected]
        if not any(json_type_matches(value, str(option)) for option in options):
            return (f"{_where(path)}: expected type "
                    f"{' or '.join(str(o) for o in options)}, "
                    f"got {json_type_name(value)}")

    if "enum" in schema:
        allowed = schema["enum"]
        if isinstance(allowed, list) and not any(
                value == option and json_type_name(value)
                == json_type_name(option) for option in allowed):
            return (f"{_where(path)}: value {value!r} is not one of the "
                    f"allowed values")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return f"{_where(path)}: {value} is less than the minimum {minimum}"
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and value > maximum:
            return (f"{_where(path)}: {value} is greater than the maximum "
                    f"{maximum}")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            return (f"{_where(path)}: string is shorter than minLength "
                    f"{min_length}")
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            return (f"{_where(path)}: string is longer than maxLength "
                    f"{max_length}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                matches = re.search(pattern, value) is not None
            except re.error:
                matches = True       # an unusable pattern cannot fail a row
            if not matches:
                return (f"{_where(path)}: string does not match pattern "
                        f"{pattern!r}")

    if isinstance(value, dict):
        for name in schema.get("required") or []:
            if name not in value:
                prefix = f"{path}." if path else ""
                return f"Missing required field: {prefix}{name}"
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, sub_schema in properties.items():
                if name in value:
                    child = f"{path}.{name}" if path else name
                    error = validate_json_schema(value[name], sub_schema,
                                                 child)
                    if error:
                        return error

    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, list):
            # draft 7 tuple validation: schema per position.
            for index, sub_schema in enumerate(items):
                if index < len(value):
                    error = validate_json_schema(value[index], sub_schema,
                                                 f"{_where(path)}[{index}]")
                    if error:
                        return error
        elif items is not None:
            for index, item in enumerate(value):
                error = validate_json_schema(item, items,
                                             f"{_where(path)}[{index}]")
                if error:
                    return error

    return None


def check_schema(cfg: TaskConfig, text: str) -> SchemaResult | None:
    """Parse and validate one response; None when no schema is configured."""
    if cfg.output_schema is None:
        return None
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        # Invalid JSON is a schema failure too (part 5).
        return SchemaResult(False, None, f"Invalid JSON: {exc}")
    error = validate_json_schema(value, cfg.output_schema)
    if error is not None:
        return SchemaResult(False, None, error)
    return SchemaResult(True, value)


# ---------------------------------------------------------------------------
# Token estimation, rate limiting, cost and progress
# ---------------------------------------------------------------------------
def estimate_tokens(text: Any) -> int:
    """`1 token ~= 0.75 words`, rounded up."""
    words = len(str(text or "").split())
    return math.ceil(words / WORDS_PER_TOKEN)


def estimate_message_tokens(messages: list[dict]) -> int:
    """The estimate for a rendered conversation (AMBIGUITIES T97)."""
    return estimate_tokens(" ".join(str(message.get("content") or "")
                                    for message in messages))


def estimate_payload_tokens(payload: dict) -> int:
    """The estimate for a request body, in either API dialect (T115)."""
    if "prompt" in payload:
        return estimate_tokens(payload.get("prompt"))
    return estimate_message_tokens(payload.get("messages") or [])


class BudgetStop(Exception):
    """Raised instead of dispatching once the cost budget is exhausted."""


class TokenReservation:
    """One entry of the sliding TPM window (T96)."""
    __slots__ = ("when", "amount")

    def __init__(self, when: float, amount: int):
        self.when = when
        self.amount = amount


class Limiter:
    """Sliding 60-second RPM and TPM windows plus a hard concurrency cap."""

    def __init__(self, rpm: int | None, tpm: int | None, max_concurrent: int):
        self.rpm = rpm
        self.tpm = tpm
        self.slot = asyncio.Semaphore(max(1, max_concurrent))
        self._lock = asyncio.Lock()
        self._requests: deque[float] = deque()
        self._tokens: deque[TokenReservation] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - RATE_WINDOW_SECONDS
        while self._requests and self._requests[0] <= cutoff:
            self._requests.popleft()
        while self._tokens and self._tokens[0].when <= cutoff:
            self._tokens.popleft()

    async def reserve(self, estimate: int) -> TokenReservation | None:
        """Admit one request, waiting until both windows have capacity.

        The admission lock is held across the wait, so requests are admitted
        in the order they arrive - which keeps rows going out in input order.
        """
        if self.rpm is None and self.tpm is None:
            return None
        async with self._lock:
            while True:
                now = time.monotonic()
                self._prune(now)
                wait = 0.0
                if self.rpm is not None and len(self._requests) >= self.rpm:
                    wait = max(wait,
                               self._requests[0] + RATE_WINDOW_SECONDS - now)
                if self.tpm is not None and self._tokens:
                    used = sum(record.amount for record in self._tokens)
                    if used + estimate > self.tpm:
                        wait = max(wait,
                                   self._tokens[0].when
                                   + RATE_WINDOW_SECONDS - now)
                if wait <= 0:
                    break
                await asyncio.sleep(min(wait, RATE_WINDOW_SECONDS) + 0.005)

            now = time.monotonic()
            self._requests.append(now)
            if self.tpm is None:
                return None
            record = TokenReservation(now, estimate)
            self._tokens.append(record)
            return record

    @staticmethod
    def settle(record: TokenReservation | None, actual: int | None) -> None:
        """Replace a reservation with the response's real token count (T96)."""
        if record is not None and actual is not None:
            record.amount = actual


class CostTracker:
    """Run-wide cost accounting and the budget kill switch (T98)."""

    def __init__(self, budget: float | None = None):
        self.prompt_cost = 0.0
        self.completion_cost = 0.0
        self.budget = budget
        self.exceeded = False

    @property
    def total(self) -> float:
        return self.prompt_cost + self.completion_cost

    @property
    def stopped(self) -> bool:
        return self.exceeded

    def add(self, prompt_tokens: int, completion_tokens: int,
            cost: CostConfig) -> None:
        self.prompt_cost += prompt_tokens / 1000 * cost.prompt_per_1k
        self.completion_cost += completion_tokens / 1000 * cost.completion_per_1k
        if self.budget is not None and self.total >= self.budget:
            self.exceeded = True

    def summary(self) -> dict:
        """The summary's `cost` object."""
        total = round(self.total, COST_DECIMALS)
        data = {
            "total": total,
            "prompt": round(self.prompt_cost, COST_DECIMALS),
            "completion": round(self.completion_cost, COST_DECIMALS),
            "budget": self.budget,
            "budget_remaining": (None if self.budget is None
                                 else round(self.budget - self.total,
                                            COST_DECIMALS)),
            "budget_exceeded": bool(self.exceeded),
        }
        return data


class Progress:
    """`--progress`: one run-wide stderr counter (T113, T114)."""

    def __init__(self, total: int, *, enabled: bool, show_eval: bool,
                 show_cost: bool, tracker: CostTracker):
        self.total = total
        self.enabled = enabled
        self.show_eval = show_eval
        self.show_cost = show_cost
        self.tracker = tracker
        self.done = 0
        self.passed = 0
        self.failed = 0
        self.calls = 0
        self.started = time.monotonic()
        self._last_emit = self.started
        self._last_done = 0
        self._step = max(1, int(total * PROGRESS_FRACTION)) if total else 1

    def record_call(self) -> None:
        self.calls += 1

    def record_row(self, passed: bool | None) -> None:
        self.done += 1
        if passed is True:
            self.passed += 1
        elif passed is False:
            self.failed += 1
        self.tick()

    def tick(self, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and (now - self._last_emit < PROGRESS_SECONDS
                          and self.done - self._last_done < self._step):
            return
        self._last_emit = now
        self._last_done = self.done
        print(self.line(now), file=sys.stderr, flush=True)

    def line(self, now: float | None = None) -> str:
        now = time.monotonic() if now is None else now
        elapsed = max(1e-9, now - self.started)
        percent = int(self.done / self.total * 100) if self.total else 100
        fields = []
        if self.show_eval:
            fields.append(f"{self.passed} passed, {self.failed} failed")
        fields.append(f"{self.calls / elapsed * 60:.1f} rpm")
        if self.show_cost:
            fields.append(f"${self.tracker.total:.2f} spent")
        fields.append(f"ETA: {self._eta(elapsed)}")
        return (f"[{self.done}/{self.total}] {percent}% complete | "
                + " | ".join(fields))

    def _eta(self, elapsed: float) -> str:
        remaining = max(0, self.total - self.done)
        if not self.done:
            return "?"
        seconds = remaining / (self.done / elapsed)
        return f"{int(round(seconds))}s"


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------
@dataclass
class Stats:
    total_api_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    first_request: float | None = None
    last_response: float | None = None

    def mark_request(self, when: float) -> None:
        if self.first_request is None or when < self.first_request:
            self.first_request = when

    def mark_response(self, when: float) -> None:
        if self.last_response is None or when > self.last_response:
            self.last_response = when

    @property
    def elapsed(self) -> float:
        if self.first_request is None or self.last_response is None:
            return 0.0
        return max(0.0, self.last_response - self.first_request)


@dataclass
class Attempt:
    """One completed API call."""
    text: str
    meta: dict
    tool_calls: list[ToolCall] = field(default_factory=list)
    message: dict | None = None      # the assistant message, in chat mode

    @property
    def detail(self) -> dict:
        """This call's entry in `meta.iterations_detail` (T91)."""
        return {key: self.meta.get(key)
                for key in ("prompt_tokens", "completion_tokens",
                            "total_tokens", "latency_ms", "finish_reason")}


@dataclass
class AgenticRun:
    """One completed agentic loop over a single row."""
    text: str | None
    tool_calls: list = field(default_factory=list)
    iterations: int = 0
    details: list = field(default_factory=list)
    finish_reason: str | None = None
    latency: float = 0.0

    @property
    def meta(self) -> dict | None:
        """Aggregated loop metadata; `None` when nothing completed (T68)."""
        if not self.details:
            return None
        return {
            "total_prompt_tokens": sum(d["prompt_tokens"] or 0
                                       for d in self.details),
            "total_completion_tokens": sum(d["completion_tokens"] or 0
                                           for d in self.details),
            "total_tokens": sum(d["total_tokens"] or 0
                                for d in self.details),
            "latency_ms": int(round(self.latency * 1000)),
            "finish_reason": self.finish_reason,
            "iterations_detail": self.details,
        }


@dataclass
class Solution:
    """One emitted solution (parsed JSON when a schema applies) and its setup."""
    text: Any
    setup: str | None


@dataclass
class MultiOutcome:
    """A Part 3 row: many solutions, one meta entry per completed attempt."""
    solutions: list[Solution] = field(default_factory=list)
    metas: list[dict] = field(default_factory=list)
    attempts: int = 0
    passed: int = 0


@dataclass
class RowOutcome:
    output: Any
    passed: bool | None
    extracted: str | None
    attempts: int
    metas: list[dict] = field(default_factory=list)
    judge_score: float | None = None
    # Agentic rows only (AMBIGUITIES T66).
    iterations: int | None = None
    tool_calls: list | None = None
    # `output_schema` rows only (AMBIGUITIES T105).
    schema_valid: bool | None = None
    schema_error: str | None = None


class ApiClient:
    def __init__(self, session, cfg: TaskConfig, stats: Stats,
                 limiter: Limiter, tracker: CostTracker, progress: Progress):
        self.session = session
        self.cfg = cfg
        self.stats = stats
        self.limiter = limiter
        self.tracker = tracker
        self.progress = progress

    @property
    def stopped(self) -> bool:
        """True once the budget is exhausted: send no new requests."""
        return self.tracker.stopped

    def build_payload(self, row: dict, setup: IclSetup | None = None) -> dict:
        return self._payload(self.cfg.system_template, self.cfg.user_template,
                             row, self.cfg.model, self.cfg.temperature,
                             setup=setup)

    def build_messages(self, row: dict,
                       setup: IclSetup | None = None) -> list[dict]:
        """The agentic loop's initial conversation (loop step 1)."""
        return self._messages(self.cfg.system_template, self.cfg.user_template,
                              row, setup=setup)

    def build_body(self, messages: list[dict], *, model: str | None = None,
                   temperature: float | None = None,
                   tools: list[ToolSpec] | None = None) -> dict:
        """One request body, in whichever API dialect the task speaks."""
        cfg = self.cfg
        model = model or cfg.model
        temperature = cfg.temperature if temperature is None else temperature

        if cfg.api_type == "completions":
            # Tool definitions are rendered into the prompt instead of being
            # sent natively; the body carries exactly four keys (T85, T87).
            rendered = with_tool_preamble(messages, tools or [])
            return {
                "model": model,
                "prompt": render_prompt(rendered, cfg.chat_template),
                "temperature": temperature,
                "max_tokens": cfg.max_tokens,
            }

        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": cfg.max_tokens,
        }
        if tools:
            body["tools"] = [tool.definition for tool in tools]
        return body

    def tool_message(self, call: ToolCall, result: str) -> dict:
        """The conversation entry recording one tool result (T71)."""
        if self.cfg.api_type == "completions":
            return {"role": "tool", "content": result}
        message = {"role": "tool", "content": result}
        if call.id is not None:
            message["tool_call_id"] = call.id
        return message

    def assistant_message(self, attempt: Attempt) -> dict:
        """The assistant tool-call message to echo back (T72)."""
        if attempt.message is not None:
            return attempt.message
        return {"role": "assistant", "content": attempt.text}

    def build_judge_payload(self, row: dict, text: str) -> dict:
        """The judge request: same server, its own prompt and model (T23)."""
        evaluation = self.cfg.evaluation
        context = dict(row)
        context[RESPONSE_PLACEHOLDER] = text
        return self._payload(evaluation.judge_system, evaluation.judge_user,
                             context, evaluation.model or self.cfg.model, 0.0)

    def _payload(self, system_template: str | None, user_template: str,
                 row: dict, model: str, temperature: float,
                 setup: IclSetup | None = None) -> dict:
        messages = self._messages(system_template, user_template, row,
                                  setup=setup)
        return self.build_body(messages, model=model, temperature=temperature)

    def _messages(self, system_template: str | None, user_template: str,
                  row: dict, setup: IclSetup | None = None) -> list[dict]:
        return compose_messages(self.cfg, system_template, user_template, row,
                                setup)

    async def complete(self, payload: dict, *,
                       hold_slot: bool = True) -> Attempt | None:
        """One logical attempt: up to MAX_REQUESTS_PER_CALL HTTP requests.

        `hold_slot=False` is for requests made inside an agentic loop, which
        already holds the row's concurrency slot for its whole lifetime.
        """
        if self.stopped:
            raise BudgetStop()
        if not hold_slot:
            return await self._complete(payload)
        async with self.limiter.slot:
            return await self._complete(payload)

    async def _complete(self, payload: dict) -> Attempt | None:
        # Reserve `estimated_prompt_tokens + max_tokens` before dispatch.
        estimate = estimate_payload_tokens(payload) + self.cfg.max_tokens
        for request_index in range(MAX_REQUESTS_PER_CALL):
            if self.stopped:
                raise BudgetStop()
            # Every HTTP request - retries included - goes through the limiter.
            record = await self.limiter.reserve(estimate)
            started = time.monotonic()
            self.stats.total_api_calls += 1
            self.progress.record_call()
            self.stats.mark_request(started)
            try:
                async with self.session.post(self.cfg.endpoint,
                                             json=payload) as response:
                    status = response.status
                    body = await response.read()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                # Transport failures are retried like a 5xx (T9).
                self.stats.mark_response(time.monotonic())
                status, body = None, b""
            finished = time.monotonic()
            self.stats.mark_response(finished)

            if status is not None and 200 <= status < 300:
                attempt = self._parse(body, finished - started,
                                      payload.get("model", self.cfg.model))
                if attempt is not None:
                    prompt_tokens = attempt.meta["prompt_tokens"] or 0
                    completion_tokens = attempt.meta["completion_tokens"] or 0
                    self.stats.total_prompt_tokens += prompt_tokens
                    self.stats.total_completion_tokens += completion_tokens
                    # Record the real usage in the TPM window and the cost.
                    self.limiter.settle(record,
                                        prompt_tokens + completion_tokens)
                    self.tracker.add(prompt_tokens, completion_tokens,
                                     self.cfg.cost)
                    return attempt
                return None  # unusable 2xx body: not retryable
            self.limiter.settle(record, 0)
            if status is not None and not (500 <= status < 600):
                return None  # 4xx and friends are not retried (T9)
            if request_index < MAX_REQUESTS_PER_CALL - 1:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
        return None

    def _parse(self, body: bytes, latency: float,
               model: str) -> Attempt | None:
        completions = self.cfg.api_type == "completions"
        message: dict | None = None
        try:
            data = json.loads(body.decode("utf-8"))
            choice = data["choices"][0]
            if completions:
                # completions responses carry `text`, not `message` (part 4)
                text = choice["text"]
            else:
                message = choice["message"]
                text = message["content"]
        except (ValueError, KeyError, IndexError, TypeError,
                UnicodeDecodeError):
            return None
        if text is None:
            text = ""

        tool_calls: list[ToolCall] = []
        if self.cfg.is_agentic:
            tool_calls = (parse_text_tool_calls(text) if completions
                          else parse_message_tool_calls(message))
        usage = data.get("usage") or {}
        meta = {
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "latency_ms": int(round(latency * 1000)),
            "finish_reason": choice.get("finish_reason"),
        }
        return Attempt(text=str(text), meta=meta, tool_calls=tool_calls,
                       message=message)


def compose_messages(cfg: TaskConfig, system_template: str | None,
                     user_template: str, row: dict,
                     setup: IclSetup | None = None) -> list[dict]:
    """Render one conversation: system message, ICL shots, then the row."""
    messages = []
    if system_template is not None:
        messages.append({"role": "system",
                         "content": render_template(system_template, row)})
    if setup is not None and cfg.icl is not None:
        # Examples sit between the system message and the final user message,
        # as alternating user/assistant turns.
        for example in cfg.icl.shots(setup):
            messages.append(
                {"role": "user",
                 "content": render_template(user_template, example.input)})
            messages.append({"role": "assistant", "content": example.output})
    messages.append({"role": "user",
                     "content": render_template(user_template, row)})
    return messages


# ---------------------------------------------------------------------------
# Row processing
# ---------------------------------------------------------------------------
async def evaluate_attempt(client: "ApiClient", row: dict,
                           text: str) -> Verdict:
    """Evaluate one generated response, dispatching on evaluation type."""
    cfg = client.cfg
    evaluation = cfg.evaluation
    assert evaluation is not None

    if evaluation.type == "script":
        return await run_script_evaluation(evaluation, row, text)

    if evaluation.type == "llm_judge":
        judge = await client.complete(client.build_judge_payload(row, text))
        if judge is None:
            # The judge call died: no score, so the row cannot pass.
            return Verdict(passed=False)
        extracted = extract_answer(judge.text, evaluation.extract)
        score = parse_score(extracted)
        passed = score is not None and score >= evaluation.threshold
        return Verdict(passed=passed, extracted=extracted, judge_score=score,
                       judge_meta=judge.meta)

    passed, extracted = evaluate(cfg, row, text)
    return Verdict(passed=passed, extracted=extracted)


def row_is_gated(cfg: TaskConfig) -> bool:
    """True when something decides `result.passed` for this task (T104)."""
    return cfg.evaluation is not None or cfg.output_schema is not None


def attach_judge_meta(meta: dict, verdict: Verdict) -> dict:
    """Fold a judge call's metadata into the attempt's `meta` object (T24)."""
    if verdict.judge_meta is not None:
        meta["judge_meta"] = verdict.judge_meta
    return meta


def choose_setup(cfg: TaskConfig, index: int) -> IclSetup | None:
    """The setup for attempt `index` of a row under the configured strategy."""
    if cfg.icl is None:
        return None
    setups = cfg.icl.setups
    if cfg.icl.strategy == "random":
        return random.choice(setups)
    if cfg.icl.strategy == "round_robin":
        # The cycle restarts for every row (AMBIGUITIES T44).
        return setups[index % len(setups)]
    return setups[0]                      # "fixed"


def plan_setups(cfg: TaskConfig) -> list[IclSetup | None]:
    """The setup to use for each attempt this row may make, in order."""
    if cfg.scheme == "greedy":
        if cfg.icl is not None and cfg.num_solutions > 1:
            # Declared order, at most once per setup; deterministic, so there
            # is nothing to gain from repeating one (T47 covers the no-ICL case).
            return list(cfg.icl.setups[:cfg.num_solutions])
        return [choose_setup(cfg, 0)]
    # `agentic` runs one independent loop per requested solution (T90).
    budget = (cfg.max_attempts if cfg.scheme == "rejection"
              else cfg.num_solutions)
    return [choose_setup(cfg, index) for index in range(budget)]


async def run_agentic(client: "ApiClient", row: dict,
                      setup: IclSetup | None = None) -> AgenticRun:
    """One agentic loop: request, run tools, repeat until text or the limit.

    The loop holds a single concurrency slot for its entire lifetime (part 5),
    so its own requests bypass the per-request slot.
    """
    if client.stopped:
        raise BudgetStop()
    async with client.limiter.slot:
        return await _run_agentic(client, row, setup)


async def _run_agentic(client: "ApiClient", row: dict,
                       setup: IclSetup | None = None) -> AgenticRun:
    cfg = client.cfg
    tools = cfg.active_tools
    messages = client.build_messages(row, setup)
    run = AgenticRun(text=None)
    started = time.monotonic()

    while run.iterations < cfg.max_iterations:
        if run.iterations and client.stopped:
            # The budget ran out mid-loop: the row is incomplete (T101).
            raise BudgetStop()
        attempt = await client.complete(client.build_body(messages,
                                                          tools=tools),
                                        hold_slot=False)
        run.iterations += 1
        if attempt is None:
            # Retries exhausted: the row failed like any part 1 row (T68).
            run.finish_reason = None
            break

        run.details.append(attempt.detail)

        if attempt.tool_calls:
            # Step 3: execute every call, then keep going (T62, T93).
            messages.append(client.assistant_message(attempt))
            for call in attempt.tool_calls:
                result = await execute_tool_call(cfg, call)
                run.tool_calls.append({
                    "iteration": run.iterations,
                    "tool": call.name,
                    "args": call.args,
                    "result": result,
                })
                messages.append(client.tool_message(call, result))
            continue

        # Step 4: final text and no tool calls.
        run.text = attempt.text
        run.finish_reason = "stop"
        break
    else:
        # Step 5: the budget ran out while the model still wanted tools.
        run.finish_reason = "max_iterations"

    run.latency = time.monotonic() - started
    return run


async def process_agentic_row(client: "ApiClient", row: dict) -> RowOutcome:
    """A single-solution agentic row (part 4 / Agentic Output)."""
    cfg = client.cfg
    run = await run_agentic(client, row)
    loop_meta = run.meta
    metas = [loop_meta] if loop_meta is not None else []

    if run.text is None:
        if run.finish_reason == "max_iterations":
            # `output` is null, so evaluation cannot pass - even when no
            # evaluation is configured (part 4 rule).
            passed: bool | None = False
        else:
            passed = False if row_is_gated(cfg) else None
        return RowOutcome(output=None, passed=passed, extracted=None,
                          attempts=1, metas=metas, iterations=run.iterations,
                          tool_calls=run.tool_calls)

    schema = check_schema(cfg, run.text)
    if schema is not None and not schema.valid:
        return RowOutcome(output=None, passed=False, extracted=None,
                          attempts=1, metas=metas, iterations=run.iterations,
                          tool_calls=run.tool_calls, schema_valid=False,
                          schema_error=schema.error)
    output = schema.value if schema is not None else run.text
    schema_valid = True if schema is not None else None

    if cfg.evaluation is None:
        return RowOutcome(output=output, passed=schema_valid, extracted=None,
                          attempts=1, metas=metas, iterations=run.iterations,
                          tool_calls=run.tool_calls,
                          schema_valid=schema_valid)

    # Evaluation runs against the final text output only.
    verdict = await evaluate_attempt(client, row, run.text)
    if metas:
        attach_judge_meta(metas[0], verdict)
    return RowOutcome(output=output, passed=verdict.passed,
                      extracted=verdict.extracted, attempts=1, metas=metas,
                      judge_score=verdict.judge_score,
                      iterations=run.iterations, tool_calls=run.tool_calls,
                      schema_valid=schema_valid)


async def process_multi(client: "ApiClient", row: dict) -> MultiOutcome:
    """Collect up to `num_solutions` solutions for one row (Part 3)."""
    cfg = client.cfg
    # Only rejection sampling gates emission on the evaluation result (T46).
    gated = cfg.scheme == "rejection"
    outcome = MultiOutcome()

    for setup in plan_setups(cfg):
        if len(outcome.solutions) >= cfg.num_solutions:
            break
        if outcome.attempts and client.stopped:
            # The budget ran out: keep the solutions collected so far (T101).
            break
        outcome.attempts += 1
        name = setup.name if setup is not None else None

        if cfg.is_agentic:
            # Each solution is an independent loop; `attempts` counts loops,
            # not the API requests inside them (part 4 rules).
            run = await run_agentic(client, row, setup)
            text, source_meta = run.text, run.meta
        else:
            attempt = await client.complete(client.build_payload(row, setup))
            text = attempt.text if attempt is not None else None
            source_meta = attempt.meta if attempt is not None else None

        if source_meta is None:
            # A dead attempt is counted and skipped (AMBIGUITIES T48).
            continue

        meta = dict(source_meta)
        meta["icl_setup"] = name
        if text is None:
            # An agentic loop that hit `max_iterations`: counted, no output
            # (AMBIGUITIES T89).
            meta["evaluation_passed"] = False if cfg.evaluation else None
            outcome.metas.append(meta)
            continue

        # `output_schema` runs before any evaluation (part 5); a solution
        # with no parsed value cannot be emitted (AMBIGUITIES T106).
        schema = check_schema(cfg, text)
        if schema is not None and not schema.valid:
            meta["schema_valid"] = False
            meta["schema_error"] = schema.error
            meta["evaluation_passed"] = False
            outcome.metas.append(meta)
            continue
        value = schema.value if schema is not None else text
        if schema is not None:
            meta["schema_valid"] = True

        if cfg.evaluation is None:
            meta["evaluation_passed"] = True if schema is not None else None
            outcome.metas.append(meta)
            outcome.solutions.append(Solution(value, name))
            outcome.passed += 1
            continue

        try:
            verdict = await evaluate_attempt(client, row, text)
        except BudgetStop:
            outcome.metas.append(meta)
            break
        meta["evaluation_passed"] = bool(verdict.passed)
        outcome.metas.append(attach_judge_meta(meta, verdict))
        if verdict.passed:
            outcome.passed += 1
        if verdict.passed or not gated:
            outcome.solutions.append(Solution(value, name))

    return outcome


async def process_row(client: "ApiClient", row: dict) -> RowOutcome | MultiOutcome:
    cfg = client.cfg
    if cfg.uses_list_format:
        return await process_multi(client, row)

    if cfg.is_agentic:
        return await process_agentic_row(client, row)

    payload = client.build_payload(row)

    if cfg.scheme == "rejection":
        return await process_rejection(client, row, payload)

    attempt = await client.complete(payload)
    if attempt is None:
        # Retries exhausted (or a non-retryable error): the row failed.
        return RowOutcome(output=None,
                          passed=False if row_is_gated(cfg) else None,
                          extracted=None, attempts=1, metas=[])

    # `output_schema` is validated before any other evaluation (part 5).
    schema = check_schema(cfg, attempt.text)
    if schema is not None and not schema.valid:
        return RowOutcome(output=None, passed=False, extracted=None,
                          attempts=1, metas=[attempt.meta],
                          schema_valid=False, schema_error=schema.error)
    output = schema.value if schema is not None else attempt.text
    schema_valid = True if schema is not None else None

    if cfg.evaluation is None:
        # With a schema and no evaluation, schema validity is the verdict (T104).
        return RowOutcome(output=output, passed=schema_valid, extracted=None,
                          attempts=1, metas=[attempt.meta],
                          schema_valid=schema_valid)

    verdict = await evaluate_attempt(client, row, attempt.text)
    return RowOutcome(output=output, passed=verdict.passed,
                      extracted=verdict.extracted, attempts=1,
                      metas=[attach_judge_meta(attempt.meta, verdict)],
                      judge_score=verdict.judge_score,
                      schema_valid=schema_valid)


async def process_rejection(client: "ApiClient", row: dict,
                            payload: dict) -> RowOutcome:
    cfg = client.cfg
    metas: list[dict] = []
    last_schema_valid: bool | None = None
    for index in range(cfg.n):
        if index and client.stopped:
            # The budget ran out: keep what this row already has (T101).
            break
        attempt = await client.complete(payload)
        if attempt is None:
            # A dead attempt fails the whole row (AMBIGUITIES T7).
            break

        # Schema failure is a failed attempt and may trigger another try.
        schema = check_schema(cfg, attempt.text)
        if schema is not None and not schema.valid:
            meta = dict(attempt.meta)
            meta["schema_valid"] = False
            meta["schema_error"] = schema.error
            metas.append(meta)
            last_schema_valid = False
            continue
        output = schema.value if schema is not None else attempt.text
        schema_valid = True if schema is not None else None
        if schema_valid:
            last_schema_valid = True

        if cfg.evaluation is None:
            # Schema-only rejection sampling (part 5).
            metas.append(dict(attempt.meta, schema_valid=True))
            return RowOutcome(output=output, passed=True, extracted=None,
                              attempts=len(metas), metas=metas,
                              schema_valid=True)

        try:
            verdict = await evaluate_attempt(client, row, attempt.text)
        except BudgetStop:
            break
        meta = attach_judge_meta(dict(attempt.meta), verdict)
        if schema_valid is not None:
            meta["schema_valid"] = True
        metas.append(meta)
        if verdict.passed:
            return RowOutcome(output=output, passed=True,
                              extracted=verdict.extracted, attempts=len(metas),
                              metas=metas, judge_score=verdict.judge_score,
                              schema_valid=schema_valid)
    return RowOutcome(output=None, passed=False, extracted=None,
                      attempts=max(1, len(metas)), metas=metas,
                      schema_valid=last_schema_valid)


def render_multi_row(cfg: TaskConfig, row: dict,
                     outcome: MultiOutcome) -> dict:
    """The Part 3 row shape: list `output`, counting `result`, list `meta`."""
    output = [{cfg.output_field: solution.text, "icl_setup": solution.setup}
              for solution in outcome.solutions]
    return {
        "input": row,
        "output": output,
        "result": {
            "passed": outcome.passed,
            "failed": outcome.attempts - outcome.passed,
            "attempts": outcome.attempts,
        },
        "meta": outcome.metas,
    }


def render_row(cfg: TaskConfig, row: dict,
               outcome: RowOutcome | MultiOutcome) -> dict:
    if isinstance(outcome, MultiOutcome):
        return render_multi_row(cfg, row, outcome)

    if outcome.output is None and not (cfg.output_schema is not None
                                       and outcome.schema_valid):
        output = None
    else:
        # A schema-valid response may legitimately parse to `null`.
        output = {cfg.output_field: outcome.output}

    if len(outcome.metas) == 0:
        meta: Any = None                 # no completed API call (T1)
    elif len(outcome.metas) == 1:
        meta = outcome.metas[0]          # one-attempt row (T2)
    else:
        meta = outcome.metas

    result: dict[str, Any] = {
        "passed": outcome.passed,
        "extracted_answer": outcome.extracted,
        "attempts": outcome.attempts,
    }
    if outcome.iterations is not None:
        # Agentic rows report their loop (AMBIGUITIES T66).
        result["iterations"] = outcome.iterations
        result["tool_calls"] = outcome.tool_calls or []
    if cfg.output_schema is not None:
        # `schema_valid` on every row of a schema task; `schema_error` only
        # when validation failed (AMBIGUITIES T105).
        result["schema_valid"] = outcome.schema_valid
        if outcome.schema_error is not None:
            result["schema_error"] = outcome.schema_error
    if cfg.evaluation is not None and cfg.evaluation.type == "llm_judge":
        # `judge_score` belongs to judge rows only (AMBIGUITIES T26).
        result["judge_score"] = outcome.judge_score

    return {
        "input": row,
        "output": output,
        "result": result,
        "meta": meta,
    }


async def process_one(client: "ApiClient", row: dict) -> dict | None:
    """One input row, rendered; `None` when the budget stopped it (T100)."""
    try:
        outcome = await process_row(client, row)
    except BudgetStop:
        return None
    rendered = render_row(client.cfg, row, outcome)
    client.progress.record_row(row_verdict(rendered))
    return rendered


async def run_rows(cfg: TaskConfig, rows: list[dict], stats: Stats,
                   tracker: CostTracker, progress: Progress) -> list[dict]:
    if not rows:
        return []

    limiter = Limiter(cfg.rpm, cfg.tpm, cfg.concurrency)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=600)
    connector = aiohttp.TCPConnector(limit=cfg.concurrency + 8)
    async with aiohttp.ClientSession(timeout=timeout,
                                     connector=connector) as session:
        client = ApiClient(session, cfg, stats, limiter, tracker, progress)
        # Tasks are created in row order and both the concurrency slot and the
        # limiter hand out admission FIFO, so requests go out in input order
        # (AMBIGUITIES T15) and every row keeps its own response.
        tasks = [asyncio.ensure_future(process_one(client, row))
                 for row in rows]
        rendered = await asyncio.gather(*tasks)

    return [row for row in rendered if row is not None]


async def progress_ticker(progress: Progress) -> None:
    """Emit the 5-second progress tick even while nothing completes."""
    while True:
        await asyncio.sleep(PROGRESS_POLL_SECONDS)
        progress.tick()


async def run_tasks(jobs: list[tuple[TaskConfig, list[dict]]],
                    tracker: CostTracker, progress: Progress
                    ) -> dict[str, tuple[list[dict], Stats]]:
    """Run every selected task in one event loop, concurrently (T38)."""
    stats = {cfg.name: Stats() for cfg, _ in jobs}
    ticker = (asyncio.ensure_future(progress_ticker(progress))
              if progress.enabled else None)
    try:
        coroutines = [run_rows(cfg, rows, stats[cfg.name], tracker, progress)
                      for cfg, rows in jobs]
        results = await asyncio.gather(*coroutines)
    finally:
        if ticker is not None:
            ticker.cancel()
            try:
                await ticker
            except asyncio.CancelledError:
                pass
            progress.tick(force=True)
    return {cfg.name: (rows, stats[cfg.name])
            for (cfg, _), rows in zip(jobs, results)}


def aggregate_stats(parts: list[Stats]) -> Stats:
    """Sum counters and span the widest first-request..last-response window."""
    total = Stats()
    for part in parts:
        total.total_api_calls += part.total_api_calls
        total.total_prompt_tokens += part.total_prompt_tokens
        total.total_completion_tokens += part.total_completion_tokens
        if part.first_request is not None:
            total.mark_request(part.first_request)
        if part.last_response is not None:
            total.mark_response(part.last_response)
    return total


def count_solutions(rows: list[dict]) -> int:
    """Total emitted solutions across rows (list rows carry several)."""
    total = 0
    for row in rows:
        output = row["output"]
        if isinstance(output, list):
            total += len(output)
        elif output is not None:
            total += 1
    return total


def row_verdict(row: dict) -> bool | None:
    """One row's verdict: True/False, or None when nothing evaluated it."""
    if isinstance(row["output"], list):
        # Part 3 row: `result.passed` is a count of passing solutions.
        return row["result"]["passed"] >= 1
    verdict = row["result"]["passed"]
    if verdict is True:
        return True
    if verdict is False or row["output"] is None:
        return False
    return None


def count_rows(rows: list[dict]) -> tuple[int, int]:
    """(passed, failed) using the Part 1 rule; list rows count once (T49)."""
    passed = 0
    failed = 0
    for row in rows:
        # No evaluation configured: a successful API row counts as passed.
        if row_verdict(row) is False:
            failed += 1
        else:
            passed += 1
    return passed, failed


def solution_fields(rows: list[dict]) -> dict:
    """The Part 3 per-task counters (AMBIGUITIES T50, T57)."""
    total_solutions = count_solutions(rows)
    average = round(total_solutions / len(rows), 2) if rows else 0.0
    return {"total_solutions": total_solutions,
            "avg_solutions_per_input": average}


def build_summary(rows: list[dict], stats: Stats,
                  cfg: TaskConfig | None = None) -> dict:
    passed, failed = count_rows(rows)

    elapsed = stats.elapsed
    throughput = (stats.total_api_calls / elapsed * 60) if elapsed > 0 else 0.0
    summary = {
        "total": len(rows),
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": stats.total_prompt_tokens,
        "total_completion_tokens": stats.total_completion_tokens,
        "total_api_calls": stats.total_api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }
    if cfg is not None and cfg.uses_list_format:
        # A single-task run has no `tasks` object; its per-task numbers belong
        # on the summary itself (T50).
        summary.update(solution_fields(rows))
    return summary


def build_multi_summary(results: dict[str, tuple[list[dict], Stats]],
                        order: list[str],
                        configs: dict[str, TaskConfig] | None = None,
                        resumed: dict[str, int] | None = None) -> dict:
    """Part 1's summary over every executed task, plus a `tasks` object."""
    all_rows = [row for name in order for row in results[name][0]]
    summary = build_summary(all_rows,
                            aggregate_stats([results[n][1] for n in order]))
    tasks: dict[str, dict] = {}
    for name in order:
        rows, stats = results[name]
        passed, failed = count_rows(rows)
        # Only the four keys the spec shows (AMBIGUITIES T34).
        entry = {
            "total": len(rows),
            "passed": passed,
            "failed": failed,
            "total_api_calls": stats.total_api_calls,
        }
        if resumed is not None:
            # Resume is applied per task output file (AMBIGUITIES T108).
            entry["resumed_from"] = resumed.get(name, 0)
        cfg = (configs or {}).get(name)
        if cfg is not None and cfg.uses_list_format:
            entry.update(solution_fields(rows))
        tasks[name] = entry
    summary["tasks"] = tasks
    return summary


# ---------------------------------------------------------------------------
# Resume, dry run and summary assembly
# ---------------------------------------------------------------------------
def read_existing_rows(path: str) -> list[dict]:
    """Parse an existing output file; a truncated tail ends the scan."""
    rows: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    break
    except OSError:
        return []
    return rows


def row_is_complete(cfg: TaskConfig, row: Any) -> bool:
    """Is a previously written row finished, or must it be redone (part 5)?"""
    if not isinstance(row, dict) or "output" not in row:
        return False
    output = row.get("output")
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    if isinstance(output, list):
        # Multi-solution row: fewer solutions than asked for means unfinished.
        return len(output) >= cfg.num_solutions
    if cfg.scheme == "rejection" or cfg.num_solutions > 1:
        # A rejection row with no passing sample is an incomplete result.
        return output is not None and result.get("passed") is not False
    return True


def resume_plan(cfg: TaskConfig, path: str,
                enabled: bool) -> tuple[int, list[dict]]:
    """(rows to skip, rows to keep) for `--resume` (AMBIGUITIES T107)."""
    if not enabled or not path or not os.path.exists(path):
        return 0, []
    rows = read_existing_rows(path)
    for index, row in enumerate(rows):
        if not row_is_complete(cfg, row):
            return index, rows[:index]
    return len(rows), rows


def prompt_word_count(cfg: TaskConfig, row: dict) -> int:
    """Words in the prompt this row would send (dry-run estimate)."""
    setup = cfg.icl.setups[0] if cfg.icl is not None else None
    messages = compose_messages(cfg, cfg.system_template, cfg.user_template,
                                row, setup)
    if cfg.api_type == "completions":
        rendered = with_tool_preamble(messages, cfg.active_tools)
        return len(render_prompt(rendered, cfg.chat_template).split())
    return len(" ".join(str(message.get("content") or "")
                        for message in messages).split())


def dry_run_report(jobs: list[tuple[TaskConfig, list[dict]]]) -> dict:
    """`--dry-run`: estimate inputs, tokens, cost and time (T109-T112)."""
    tasks: dict[str, dict] = {}
    total_inputs = 0
    total_tokens = 0.0
    total_cost = 0.0
    total_minutes = 0.0
    paced = False

    for cfg, rows in jobs:
        count = len(rows)
        if count:
            avg_words = sum(prompt_word_count(cfg, row)
                            for row in rows) / count
        else:
            avg_words = 0.0
        est_prompt = avg_words * DRY_RUN_TOKEN_FACTOR * count
        est_completion = cfg.max_tokens * count
        est_total = est_prompt + est_completion
        est_cost = (est_prompt / 1000 * cfg.cost.prompt_per_1k
                    + est_completion / 1000 * cfg.cost.completion_per_1k)
        tasks[cfg.name] = {
            "inputs": count,
            "est_prompt_tokens": round(est_prompt, 4),
            "est_completion_tokens": est_completion,
            "est_total_tokens": round(est_total, 4),
            "est_cost": round(est_cost, COST_DECIMALS),
        }
        total_inputs += count
        total_tokens += est_total
        total_cost += est_cost
        if cfg.rpm:
            paced = True
            total_minutes += count * cfg.avg_attempts / cfg.rpm

    return {
        "tasks": tasks,
        "total_inputs": total_inputs,
        "est_total_tokens": round(total_tokens, 4),
        "est_total_cost": round(total_cost, COST_DECIMALS),
        "est_time_minutes": round(total_minutes, 6) if paced else None,
    }


def finish_summary(summary: dict, resumed_from: int | None,
                   tracker: CostTracker, cost_configured: bool) -> dict:
    """Fold `resumed_from` and the `cost` object into a summary."""
    if resumed_from is not None:
        rebuilt: dict[str, Any] = {}
        for key, value in summary.items():
            rebuilt[key] = value
            if key == "total":
                rebuilt["resumed_from"] = resumed_from
        summary = rebuilt
    if cost_configured:
        summary["cost"] = tracker.summary()
    return summary


def prepare_output_dir(path: str) -> str:
    """`--output` must be a directory for multi-task configs (T32)."""
    if os.path.exists(path) and not os.path.isdir(path):
        raise UserError(
            f"output path is not a directory: {path}; multi-task configs "
            f"write one file per task into an output directory")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise UserError(f"could not create output directory {path}: {exc}")
    return path


def write_output(path: str, rows: list[dict]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise UserError(f"could not write output file {path}: {exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class Parser(argparse.ArgumentParser):
    """argparse, but usage errors exit 1 - the spec documents only 0 and 1."""

    def error(self, message: str):  # noqa: D102
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(
        prog="rejector.py",
        description="Run a YAML-configured generation task against an "
                    "OpenAI-compatible chat or text completions API.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run a task over a JSONL input file")
    run.set_defaults(command="run")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument(
        "--input", action="append", default=None, metavar="[TASK=]PATH",
        help="JSONL input file; repeat as '<task>=<path>' for multi-task "
             "configs")
    run.add_argument("--input-dir", dest="input_dir", default=None,
                     metavar="DIR",
                     help="directory holding one '<task_name>.jsonl' per task")
    run.add_argument("--output", required=True,
                     help="JSONL output file, or output directory for "
                          "multi-task configs")
    run.add_argument("--task", action="append", default=None, dest="task",
                     metavar="NAME",
                     help="run only the named task; repeatable")
    run.add_argument("--eval-model", dest="eval_model", default=None,
                     help="override the judge model for selected llm_judge "
                          "tasks")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--tpm", type=int, default=None,
                     help="sliding 60-second token budget")
    run.add_argument("--max-concurrent", dest="max_concurrent", type=int,
                     default=None, help="hard cap on in-flight requests")
    run.add_argument("--budget", type=float, default=None,
                     help="stop sending requests once this cost is reached")
    run.add_argument("--resume", action="store_true",
                     help="skip input rows already present in the output file")
    run.add_argument("--dry-run", dest="dry_run", action="store_true",
                     help="estimate cost and time without calling the API")
    run.add_argument("--progress", action="store_true",
                     help="print progress updates to stderr")
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", choices=list(SCHEMES), default=None)
    run.add_argument("--api-type", dest="api_type", choices=list(API_TYPES),
                     default=None,
                     help="send chat or plain completions requests")
    run.add_argument("--chat-template", dest="chat_template",
                     choices=list(CHAT_TEMPLATES), default=None,
                     help="prompt template used in completions mode")
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    run.add_argument("--num-solutions", dest="num_solutions", type=int,
                     default=None,
                     help="number of solutions to collect per input row")
    run.add_argument("--icl-strategy", dest="icl_strategy",
                     choices=list(ICL_STRATEGIES), default=None,
                     help="override 'icl.strategy' for selected tasks")
    run.add_argument("--icl-k", dest="icl_k", type=int, default=None,
                     help="override 'icl.k' for selected tasks")
    return parser


def split_input_spec(value: str, known: set[str]) -> tuple[str | None, str]:
    """Split `--input` into (task name or None, path).

    A value is a mapping only when the text before the first `=` names a task
    in the config; that keeps ordinary paths containing `=` working (T40).
    """
    if "=" in value:
        name, _, path = value.partition("=")
        if name in known:
            return name, path
    return None, value


def resolve_inputs(args: argparse.Namespace, names: list[str],
                   selected: list[str], is_multi: bool) -> dict[str, str]:
    """Map each selected task to its input file path."""
    known = set(names)
    inputs = list(args.input or [])
    mapping: dict[str, str] = {}

    if args.input_dir is not None:
        if inputs:
            raise UserError(
                "--input and --input-dir are alternative modes; "
                "do not combine them")
        if not os.path.isdir(args.input_dir):
            raise UserError(f"input directory not found: {args.input_dir}")
        for name in selected:
            mapping[name] = os.path.join(args.input_dir, f"{name}.jsonl")
        return mapping

    if not inputs:
        raise UserError("--input or --input-dir is required")

    if not is_multi:
        if len(inputs) > 1:
            raise UserError(
                "a single-task config takes exactly one --input")
        _, path = split_input_spec(inputs[0], known)
        return {selected[0]: path}

    for value in inputs:
        name, path = split_input_spec(value, known)
        if name is None:
            raise UserError(
                f"--input {value!r}: a multi-task config needs "
                f"'<task>=<path>'; known tasks: {', '.join(names)}")
        # Mappings for unselected tasks are simply ignored (T31).
        if name in selected:
            mapping[name] = path
    return mapping


def select_tasks(args: argparse.Namespace, names: list[str]) -> list[str]:
    wanted = args.task
    if not wanted:
        return list(names)
    known = set(names)
    for name in wanted:
        if name not in known:
            raise UserError(
                f"unknown task {name!r}; known tasks: {', '.join(names)}")
    # Keep the config's ordering, without duplicates.
    return [name for name in names if name in set(wanted)]


def command_run(args: argparse.Namespace) -> int:
    if aiohttp is None:  # pragma: no cover
        raise UserError("missing dependency 'aiohttp'; "
                        "install it with: pip install -r requirements.txt")

    definitions, is_multi = load_task_definitions(load_config_file(args.config))
    names = list(definitions)
    selected = select_tasks(args, names)
    inputs = resolve_inputs(args, names, selected, is_multi)

    # Build and validate every selected task before issuing any request (T8);
    # unselected tasks are never looked at (T30).
    config_dir = os.path.dirname(os.path.abspath(args.config))
    jobs: list[tuple[TaskConfig, list[dict]]] = []
    for name in selected:
        label = f"tasks.{name}" if is_multi else "task"
        cfg = build_task_config(name, definitions[name], args, label,
                                config_dir)
        if name not in inputs:
            raise UserError(f"task {name!r}: no input file given; pass "
                            f"--input {name}=<path> or --input-dir <dir>")
        rows = load_rows(inputs[name])
        validate_rows(cfg, rows)
        jobs.append((cfg, rows))

    if args.dry_run:
        # Config and inputs are validated above; no API call is made.
        print(json.dumps(dry_run_report(jobs)))
        return EXIT_OK

    if is_multi:
        output_dir = prepare_output_dir(args.output)
        paths = {cfg.name: os.path.join(output_dir, f"{cfg.name}.jsonl")
                 for cfg, _ in jobs}
    else:
        paths = {jobs[0][0].name: args.output}

    # `--resume`: skip the leading rows the output file already covers.
    resumed: dict[str, int] = {}
    kept: dict[str, list[dict]] = {}
    pending: list[tuple[TaskConfig, list[dict]]] = []
    for cfg, rows in jobs:
        skip, keep = resume_plan(cfg, paths[cfg.name], args.resume)
        resumed[cfg.name] = skip
        kept[cfg.name] = keep
        pending.append((cfg, rows[skip:]))

    budgets = [cfg.cost.budget for cfg, _ in jobs
               if cfg.cost.budget is not None]
    tracker = CostTracker(budget=min(budgets) if budgets else None)
    cost_configured = any(cfg.cost.configured for cfg, _ in jobs)
    progress = Progress(
        total=sum(len(rows) for _, rows in pending),
        enabled=bool(args.progress),
        show_eval=any(row_is_gated(cfg) for cfg, _ in jobs),
        show_cost=cost_configured,
        tracker=tracker)

    results = asyncio.run(run_tasks(pending, tracker, progress))

    configs = {cfg.name: cfg for cfg, _ in jobs}
    total_resumed = sum(resumed.values()) if args.resume else None
    if is_multi:
        for name in selected:
            write_output(paths[name], kept[name] + results[name][0])
        summary = build_multi_summary(results, selected, configs,
                                      resumed if args.resume else None)
    else:
        name = selected[0]
        rows, stats = results[name]
        write_output(args.output, kept[name] + rows)
        summary = build_summary(rows, stats, configs.get(name))

    print(json.dumps(finish_summary(summary, total_resumed, tracker,
                                    cost_configured)))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return command_run(args)
        parser.error(f"unknown command {args.command!r}")
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover
        print("error: interrupted", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
