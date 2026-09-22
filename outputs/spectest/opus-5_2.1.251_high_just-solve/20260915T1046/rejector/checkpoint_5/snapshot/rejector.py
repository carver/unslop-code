#!/usr/bin/env python3
"""rejector - run YAML-configured generation tasks against an OpenAI-compatible API.

Single task (part 1):
    python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl

Multiple named tasks (part 2):
    python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --output results/
    python rejector.py run --config multi.yaml --input-dir data/ --output results/

Agentic tool loops and /v1/completions (part 4):
    python rejector.py run --config agentic.yaml --input data.jsonl --output results.jsonl
    python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl \
        --api-type completions --chat-template llama3
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
import string
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx
import yaml

EXIT_OK = 0
EXIT_ERROR = 1

MAX_RETRIES = 3  # retries after the initial attempt, for HTTP 5xx / transport errors
SCHEMES = ("greedy", "sample", "rejection", "agentic")
EVAL_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")
ICL_STRATEGIES = ("fixed", "random", "round_robin")
API_TYPES = ("chat", "completions")
CHAT_TEMPLATES = ("chatml", "llama3", "mistral", "zephyr")
TOOL_HANDLERS = ("echo", "static_map", "script")

DEFAULT_MAX_ITERATIONS = 10
TOOL_TIMEOUT = 10.0  # seconds a `script` tool handler may run
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)

RESPONSE_KEY = "__response__"
RESPONSE_PLACEHOLDER = "{" + RESPONSE_KEY + "}"
SCRIPT_TIMEOUT = 10.0  # seconds; a timeout is a failed evaluation

WORDS_PER_TOKEN = 0.75  # prompt estimate before a request: 1 token ~= 0.75 words
DRY_RUN_TOKENS_PER_WORD = 1.33  # dry-run estimate: average word count * 1.33
RATE_WINDOW = 60.0  # seconds; RPM and TPM are sliding windows of this width
DEFAULT_CONCURRENCY_BASE = 60  # row concurrency basis when no rpm is configured
COST_DIGITS = 6  # cost values are rounded to this many decimals in the summary
JSON_TYPES = ("object", "array", "string", "number", "integer", "boolean", "null")


class ConfigError(Exception):
    """Configuration or input problem: reported on stderr, exit code 1."""


class BudgetStop(Exception):
    """Raised instead of dispatching a request once the cost budget is spent."""


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


@dataclass
class Evaluation:
    type: str
    answer_field: str | None = None
    extract: str = "full"
    extract_given: bool = False
    pattern: str | None = None
    regex: re.Pattern[str] | None = None
    # script
    command_template: str | None = None
    success_exit_code: int = 0
    # llm_judge
    judge_system: str | None = None
    judge_user: str | None = None
    threshold: float = 0.0
    model: str | None = None
    judge_temperature: float = 0.0
    judge_max_tokens: int | None = None


@dataclass
class Tool:
    """One callable tool: its JSON-schema declaration plus a local handler."""

    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    handler_type: str = "echo"
    # static_map
    mapping: dict = field(default_factory=dict)
    default: str = "NOT_FOUND"
    # script
    command: str | None = None
    arg_field: str | None = None

    @property
    def key_field(self) -> str | None:
        """The first required parameter, used as the `static_map` lookup key."""
        if not isinstance(self.parameters, dict):
            return None
        required = self.parameters.get("required")
        if isinstance(required, list) and required:
            return str(required[0])
        properties = self.parameters.get("properties")
        if isinstance(properties, dict) and properties:
            return str(next(iter(properties)))
        return None

    def definition(self) -> dict:
        """OpenAI `tools` entry sent with chat requests."""
        parameters = self.parameters or {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


@dataclass
class IclExample:
    """One in-context example: a row-shaped input plus the assistant reply."""

    input: dict
    output: str


@dataclass
class IclSetup:
    name: str
    examples: list[IclExample] = field(default_factory=list)
    # alternating user/assistant turns, built once from the first `k` examples
    messages: list[dict] = field(default_factory=list)


@dataclass
class IclConfig:
    setups: list[IclSetup]
    strategy: str = "fixed"
    k: int | None = None  # None means "all examples of the selected setup"


@dataclass
class RateLimits:
    """Sliding-window throughput limits for one task."""

    rpm: int | None = None
    tpm: int | None = None
    max_concurrent: int | None = None


@dataclass
class CostConfig:
    """Per-1k-token prices plus an optional spend budget."""

    prompt_cost_per_1k: float = 0.0
    completion_cost_per_1k: float = 0.0
    budget: float | None = None
    configured: bool = False  # any cost key was given (config or --budget)

    def call_cost(self, prompt_tokens: int, completion_tokens: int) -> tuple[float, float]:
        return (
            prompt_tokens / 1000.0 * self.prompt_cost_per_1k,
            completion_tokens / 1000.0 * self.completion_cost_per_1k,
        )


@dataclass
class Config:
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
    output_field: str
    evaluation: Evaluation | None = None
    icl: IclConfig | None = None
    num_solutions: int = 1
    max_attempts: int | None = None
    api_type: str = "chat"
    chat_template: str = "chatml"
    tools: list[Tool] = field(default_factory=list)
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    rate_limits: RateLimits = field(default_factory=RateLimits)
    cost: CostConfig = field(default_factory=CostConfig)
    output_schema: dict | None = None

    @property
    def tpm(self) -> int | None:
        return self.rate_limits.tpm

    @property
    def max_concurrent(self) -> int | None:
        return self.rate_limits.max_concurrent

    @property
    def list_format(self) -> bool:
        """Part 3 output shape: a list of solutions and one meta entry per attempt."""
        return self.icl is not None or self.num_solutions > 1

    @property
    def is_agentic(self) -> bool:
        return self.scheme == "agentic"



def _require_mapping(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"config: '{what}' must be a mapping")
    return value


def _as_int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"config: '{what}' must be an integer")
    try:
        ivalue = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"config: '{what}' must be an integer, got {value!r}") from None
    return ivalue


def _as_float(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"config: '{what}' must be a number")
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"config: '{what}' must be a number, got {value!r}") from None


def deep_merge(base: dict, override: dict) -> dict:
    """Recursive mapping merge: override wins, nested mappings are merged."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def template_fields(template: str, what: str) -> list[str]:
    """Field names referenced by {placeholders} in a template."""
    fields: list[str] = []
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise ConfigError(f"config: invalid placeholder syntax in {what}: {exc}") from None
    for _literal, name, _spec, _conv in parsed:
        if name is None:
            continue
        if name == "":
            raise ConfigError(f"config: positional placeholder '{{}}' not supported in {what}")
        root = name.split(".")[0].split("[")[0]
        if not root:
            raise ConfigError(f"config: invalid placeholder '{{{name}}}' in {what}")
        if root not in fields:
            fields.append(root)
    return fields


def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse YAML config {path}: {exc}") from None
    if raw is None:
        raise ConfigError(f"config file is empty: {path}")
    if not isinstance(raw, dict):
        raise ConfigError("config: top level must be a mapping with a 'task' or 'tasks' key")
    return raw


def is_multi_config(raw: dict) -> bool:
    """A top-level 'task' key means the part 1 single-task format."""
    return "task" not in raw and "tasks" in raw


def build_config(
    task: dict,
    args: argparse.Namespace,
    name: str,
    prefix: str,
    config_dir: str = ".",
) -> Config:
    """Build one task's config. `prefix` labels the section in error messages.

    `config_dir` is the directory of the YAML file; ICL example files resolve
    against it.
    """
    api_url = args.api_url if args.api_url is not None else task.get("api_url")
    if api_url is None or str(api_url).strip() == "":
        raise ConfigError(f"config: '{prefix}.api_url' is required (or pass --api-url)")
    api_url = str(api_url).strip().rstrip("/")

    model = args.model if args.model is not None else task.get("model")
    if model is None or str(model).strip() == "":
        raise ConfigError(f"config: '{prefix}.model' is required (or pass --model)")
    model = str(model)

    rate_limits = build_rate_limits(task, args, prefix)
    rpm = rate_limits.rpm
    cost = build_cost(task, args, prefix)
    output_schema = build_output_schema(task.get("output_schema"), prefix)

    if "prompt" not in task:
        raise ConfigError(f"config: missing required section '{prefix}.prompt'")
    prompt = _require_mapping(task["prompt"], f"{prefix}.prompt")
    if "user" not in prompt or prompt["user"] is None:
        raise ConfigError(f"config: '{prefix}.prompt.user' is required")
    user_template = str(prompt["user"])
    system_template = None if prompt.get("system") is None else str(prompt["system"])

    generation = _require_mapping(task.get("generation", {}) or {}, f"{prefix}.generation")

    scheme = args.scheme if args.scheme is not None else generation.get("scheme", "greedy")
    scheme = str(scheme).strip()
    if scheme not in SCHEMES:
        raise ConfigError(
            f"config: '{prefix}.generation.scheme' must be one of {', '.join(SCHEMES)}, "
            f"got {scheme!r}"
        )

    if args.temperature is not None:
        temperature = float(args.temperature)
    elif generation.get("temperature") is not None:
        temperature = _as_float(generation["temperature"], f"{prefix}.generation.temperature")
    else:
        temperature = 0.0

    max_tokens_raw = (
        args.max_tokens if args.max_tokens is not None else generation.get("max_tokens", 512)
    )
    max_tokens = _as_int(max_tokens_raw, f"{prefix}.generation.max_tokens")
    if max_tokens <= 0:
        raise ConfigError(f"config: '{prefix}.generation.max_tokens' must be > 0, got {max_tokens}")

    n_raw = args.n if args.n is not None else generation.get("n", 1)
    n = _as_int(n_raw, f"{prefix}.generation.n")
    if n <= 0:
        raise ConfigError(f"config: '{prefix}.generation.n' must be > 0, got {n}")

    if getattr(args, "num_solutions", None) is not None:
        num_solutions = _as_int(args.num_solutions, "--num-solutions")
        num_label = "--num-solutions"
    else:
        raw_num = task.get("num_solutions")
        if raw_num is None:
            raw_num = generation.get("num_solutions")
        num_solutions = 1 if raw_num is None else _as_int(raw_num, f"{prefix}.num_solutions")
        num_label = f"{prefix}.num_solutions"
    if num_solutions <= 0:
        raise ConfigError(f"config: '{num_label}' must be > 0, got {num_solutions}")

    raw_max_attempts = generation.get("max_attempts")
    if raw_max_attempts is None:
        raw_max_attempts = task.get("max_attempts")
    if raw_max_attempts is None:
        max_attempts = None
    else:
        max_attempts = _as_int(raw_max_attempts, f"{prefix}.generation.max_attempts")
        if max_attempts <= 0:
            raise ConfigError(
                f"config: '{prefix}.generation.max_attempts' must be > 0, got {max_attempts}"
            )

    icl = build_icl(task.get("icl"), args, prefix, config_dir)

    api_type_raw = getattr(args, "api_type", None)
    api_type_label = "--api-type"
    if api_type_raw is None:
        api_type_raw = task.get("api_type", "chat")
        api_type_label = f"{prefix}.api_type"
    api_type = str(api_type_raw or "chat").strip()
    if api_type not in API_TYPES:
        raise ConfigError(
            f"config: '{api_type_label}' must be one of {', '.join(API_TYPES)}, got {api_type!r}"
        )

    template_raw = getattr(args, "chat_template", None)
    template_label = "--chat-template"
    if template_raw is None:
        template_raw = task.get("chat_template", "chatml")
        template_label = f"{prefix}.chat_template"
    chat_template = str(template_raw or "chatml").strip()
    if chat_template not in CHAT_TEMPLATES:
        raise ConfigError(
            f"config: '{template_label}' must be one of {', '.join(CHAT_TEMPLATES)}, "
            f"got {chat_template!r}"
        )

    raw_iterations = generation.get("max_iterations")
    if raw_iterations is None:
        raw_iterations = task.get("max_iterations")
    if raw_iterations is None:
        max_iterations = DEFAULT_MAX_ITERATIONS
    else:
        max_iterations = _as_int(raw_iterations, f"{prefix}.generation.max_iterations")
        if max_iterations <= 0:
            raise ConfigError(
                f"config: '{prefix}.generation.max_iterations' must be > 0, got {max_iterations}"
            )

    tools = build_tools(task.get("tools"), prefix)

    if scheme == "greedy":
        temperature = 0.0
        n = 1
    elif scheme == "agentic":
        # the loop drives the number of requests; `n` plays no role
        n = 1
    elif scheme == "sample":
        if temperature <= 0:
            raise ConfigError(
                f"config: scheme 'sample' requires '{prefix}.generation.temperature' > 0, "
                f"got {temperature}"
            )
        n = 1
    else:  # rejection
        if temperature <= 0:
            raise ConfigError(
                f"config: scheme 'rejection' requires '{prefix}.generation.temperature' > 0, "
                f"got {temperature}"
            )

    evaluation = build_evaluation(
        task.get("evaluation"), scheme, prefix, has_schema=output_schema is not None
    )
    if evaluation is not None and evaluation.type == "llm_judge":
        if getattr(args, "eval_model", None):
            evaluation.model = str(args.eval_model)
        if not evaluation.model:
            evaluation.model = model

    output_field_raw = task.get("output_field", "output")
    if output_field_raw is None or str(output_field_raw).strip() == "":
        raise ConfigError(f"config: '{prefix}.output_field' must be a non-empty string")
    output_field = str(output_field_raw)

    # validates placeholder syntax up front
    template_fields(user_template, f"{prefix}.prompt.user")
    if system_template is not None:
        template_fields(system_template, f"{prefix}.prompt.system")

    if icl is not None:
        build_icl_messages(icl, user_template, prefix)

    if scheme == "rejection" and not (num_solutions == 1 and icl is None):
        # part 3 rejection is bounded by max_attempts, not by generation.n
        if max_attempts is None:
            max_attempts = 3 * num_solutions

    return Config(
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
        output_field=output_field,
        evaluation=evaluation,
        icl=icl,
        num_solutions=num_solutions,
        max_attempts=max_attempts,
        api_type=api_type,
        chat_template=chat_template,
        tools=tools,
        max_iterations=max_iterations,
        rate_limits=rate_limits,
        cost=cost,
        output_schema=output_schema,
    )


def _positive_int(value: Any, what: str) -> int:
    parsed = _as_int(value, what)
    if parsed <= 0:
        raise ConfigError(f"config: '{what}' must be > 0, got {parsed}")
    return parsed


def build_rate_limits(task: dict, args: argparse.Namespace, prefix: str) -> RateLimits:
    """rate_limits section + legacy top-level `rpm` + CLI overrides.

    An omitted `rpm` disables request-rate limiting for the task; the same holds
    for `tpm` and `max_concurrent`.
    """
    section = _require_mapping(task.get("rate_limits") or {}, f"{prefix}.rate_limits")

    rpm: int | None
    if getattr(args, "rpm", None) is not None:
        rpm = _positive_int(args.rpm, "--rpm")
    elif section.get("rpm") is not None:
        rpm = _positive_int(section["rpm"], f"{prefix}.rate_limits.rpm")
    elif task.get("rpm") is not None:
        rpm = _positive_int(task["rpm"], f"{prefix}.rpm")
    else:
        rpm = None

    tpm: int | None
    if getattr(args, "tpm", None) is not None:
        tpm = _positive_int(args.tpm, "--tpm")
    elif section.get("tpm") is not None:
        tpm = _positive_int(section["tpm"], f"{prefix}.rate_limits.tpm")
    elif task.get("tpm") is not None:
        tpm = _positive_int(task["tpm"], f"{prefix}.tpm")
    else:
        tpm = None

    max_concurrent: int | None
    if getattr(args, "max_concurrent", None) is not None:
        max_concurrent = _positive_int(args.max_concurrent, "--max-concurrent")
    elif section.get("max_concurrent") is not None:
        max_concurrent = _positive_int(
            section["max_concurrent"], f"{prefix}.rate_limits.max_concurrent"
        )
    elif task.get("max_concurrent") is not None:
        max_concurrent = _positive_int(task["max_concurrent"], f"{prefix}.max_concurrent")
    else:
        max_concurrent = None

    return RateLimits(rpm=rpm, tpm=tpm, max_concurrent=max_concurrent)


def build_cost(task: dict, args: argparse.Namespace, prefix: str) -> CostConfig:
    """cost section + `--budget`; absent entirely means no cost accounting."""
    section = _require_mapping(task.get("cost") or {}, f"{prefix}.cost")
    cost = CostConfig()

    for key in ("prompt_cost_per_1k", "completion_cost_per_1k"):
        if section.get(key) is None:
            continue
        value = _as_float(section[key], f"{prefix}.cost.{key}")
        if value < 0:
            raise ConfigError(f"config: '{prefix}.cost.{key}' must be >= 0, got {value}")
        setattr(cost, key, value)
        cost.configured = True

    if getattr(args, "budget", None) is not None:
        cost.budget = _as_float(args.budget, "--budget")
        cost.configured = True
    elif section.get("budget") is not None:
        cost.budget = _as_float(section["budget"], f"{prefix}.cost.budget")
        cost.configured = True
    if cost.budget is not None and cost.budget < 0:
        raise ConfigError(f"config: '{prefix}.cost.budget' must be >= 0, got {cost.budget}")

    if section:
        # any `cost` section at all turns cost accounting on for the task
        cost.configured = True

    return cost


def build_output_schema(raw: Any, prefix: str) -> dict | None:
    """Validate the shape of an `output_schema` block (JSON Schema draft 7 subset)."""
    if raw is None:
        return None
    schema = _require_mapping(raw, f"{prefix}.output_schema")
    _check_schema(schema, f"{prefix}.output_schema")
    return schema


def _check_schema(schema: Any, where: str) -> None:
    if not isinstance(schema, dict):
        raise ConfigError(f"config: '{where}' must be a mapping")
    types = schema.get("type")
    if types is not None:
        for name in types if isinstance(types, list) else [types]:
            if str(name) not in JSON_TYPES:
                raise ConfigError(
                    f"config: '{where}.type' must be one of "
                    f"{', '.join(sorted(JSON_TYPES))}, got {name!r}"
                )
    required = schema.get("required")
    if required is not None and not isinstance(required, list):
        raise ConfigError(f"config: '{where}.required' must be a list")
    pattern = schema.get("pattern")
    if pattern is not None:
        try:
            re.compile(str(pattern))
        except re.error as exc:
            raise ConfigError(f"config: '{where}.pattern' is not a valid regex: {exc}") from None
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ConfigError(f"config: '{where}.properties' must be a mapping")
        for name, sub in properties.items():
            _check_schema(sub, f"{where}.properties.{name}")
    items = schema.get("items")
    if items is not None:
        if isinstance(items, list):
            for position, sub in enumerate(items):
                _check_schema(sub, f"{where}.items[{position}]")
        else:
            _check_schema(items, f"{where}.items")


def build_evaluation(
    raw: Any, scheme: str, prefix: str = "task", has_schema: bool = False
) -> Evaluation | None:
    if raw is None:
        if scheme == "rejection" and not has_schema:
            # rejection sampling may instead be gated by `output_schema` alone
            raise ConfigError(f"config: '{prefix}.evaluation' is required for scheme 'rejection'")
        return None

    section = _require_mapping(raw, f"{prefix}.evaluation")
    eval_type = section.get("type")
    if eval_type is None:
        raise ConfigError(f"config: '{prefix}.evaluation.type' is required")
    eval_type = str(eval_type).strip()
    if eval_type not in EVAL_TYPES:
        raise ConfigError(
            f"config: '{prefix}.evaluation.type' must be one of {', '.join(EVAL_TYPES)}, "
            f"got {eval_type!r}"
        )

    answer_field = section.get("answer_field")
    if answer_field is not None:
        answer_field = str(answer_field)

    extract_given = section.get("extract") is not None
    default_extract = "first_number" if eval_type == "llm_judge" else "full"
    extract = section.get("extract") if extract_given else default_extract
    extract = str(extract).strip()
    if extract not in EXTRACT_METHODS:
        raise ConfigError(
            f"config: '{prefix}.evaluation.extract' must be one of {', '.join(EXTRACT_METHODS)}, "
            f"got {extract!r}"
        )

    evaluation = Evaluation(
        type=eval_type,
        answer_field=answer_field,
        extract=extract,
        extract_given=extract_given,
    )

    if eval_type in ("exact_match", "contains"):
        if not answer_field:
            raise ConfigError(
                f"config: evaluation type '{eval_type}' requires '{prefix}.evaluation.answer_field'"
            )
    elif eval_type == "regex":
        pattern = section.get("pattern")
        if pattern is None or str(pattern) == "":
            raise ConfigError(
                f"config: evaluation type 'regex' requires '{prefix}.evaluation.pattern'"
            )
        pattern = str(pattern)
        try:
            evaluation.regex = re.compile(pattern, re.MULTILINE | re.DOTALL)
        except re.error as exc:
            raise ConfigError(f"config: invalid '{prefix}.evaluation.pattern': {exc}") from None
        evaluation.pattern = pattern
    elif eval_type == "script":
        command = section.get("command_template")
        if command is None or str(command).strip() == "":
            raise ConfigError(
                f"config: evaluation type 'script' requires '{prefix}.evaluation.command_template'"
            )
        evaluation.command_template = str(command)
        template_fields(evaluation.command_template, f"{prefix}.evaluation.command_template")
        code = section.get("success_exit_code", 0)
        evaluation.success_exit_code = _as_int(
            0 if code is None else code, f"{prefix}.evaluation.success_exit_code"
        )
    else:  # llm_judge
        if section.get("judge_prompt") is None:
            raise ConfigError(
                f"config: evaluation type 'llm_judge' requires '{prefix}.evaluation.judge_prompt'"
            )
        judge = _require_mapping(section["judge_prompt"], f"{prefix}.evaluation.judge_prompt")
        if judge.get("user") is None:
            raise ConfigError(f"config: '{prefix}.evaluation.judge_prompt.user' is required")
        evaluation.judge_user = str(judge["user"])
        evaluation.judge_system = None if judge.get("system") is None else str(judge["system"])
        template_fields(evaluation.judge_user, f"{prefix}.evaluation.judge_prompt.user")
        if evaluation.judge_system is not None:
            template_fields(evaluation.judge_system, f"{prefix}.evaluation.judge_prompt.system")

        if section.get("threshold") is None:
            raise ConfigError(
                f"config: evaluation type 'llm_judge' requires '{prefix}.evaluation.threshold'"
            )
        evaluation.threshold = _as_float(section["threshold"], f"{prefix}.evaluation.threshold")

        judge_model = section.get("model")
        evaluation.model = None if judge_model is None else str(judge_model)
        if section.get("temperature") is not None:
            evaluation.judge_temperature = _as_float(
                section["temperature"], f"{prefix}.evaluation.temperature"
            )
        if section.get("max_tokens") is not None:
            evaluation.judge_max_tokens = _as_int(
                section["max_tokens"], f"{prefix}.evaluation.max_tokens"
            )
            if evaluation.judge_max_tokens <= 0:
                raise ConfigError(f"config: '{prefix}.evaluation.max_tokens' must be > 0")

    return evaluation



# --------------------------------------------------------------------------
# tools (agentic scheme)
# --------------------------------------------------------------------------


def build_tools(raw: Any, prefix: str = "task") -> list[Tool]:
    """Parse the optional `tools` list of an agentic task."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"config: '{prefix}.tools' must be a list")

    tools: list[Tool] = []
    seen: set[str] = set()
    for position, item in enumerate(raw):
        where = f"{prefix}.tools[{position}]"
        section = _require_mapping(item, where)
        name = section.get("name")
        if name is None or str(name).strip() == "":
            raise ConfigError(f"config: '{where}' requires a non-empty 'name'")
        name = str(name).strip()
        if name in seen:
            raise ConfigError(f"config: duplicate tool name {name!r} in '{prefix}.tools'")
        seen.add(name)

        description = section.get("description")
        description = "" if description is None else str(description)

        parameters = section.get("parameters")
        if parameters is None:
            parameters = {"type": "object", "properties": {}}
        parameters = _require_mapping(parameters, f"{where}.parameters")

        handler_raw = section.get("handler")
        handler = {} if handler_raw is None else _require_mapping(handler_raw, f"{where}.handler")
        handler_type = str(handler.get("type", "echo") or "echo").strip()
        if handler_type not in TOOL_HANDLERS:
            raise ConfigError(
                f"config: '{where}.handler.type' must be one of {', '.join(TOOL_HANDLERS)}, "
                f"got {handler_type!r}"
            )

        tool = Tool(
            name=name,
            description=description,
            parameters=dict(parameters),
            handler_type=handler_type,
        )

        if handler_type == "static_map":
            mapping = handler.get("mapping")
            if mapping is None:
                mapping = {}
            mapping = _require_mapping(mapping, f"{where}.handler.mapping")
            tool.mapping = {str(key): value for key, value in mapping.items()}
            default = handler.get("default")
            tool.default = "NOT_FOUND" if default is None else str(default)
        elif handler_type == "script":
            command = handler.get("command")
            if command is None or str(command).strip() == "":
                raise ConfigError(
                    f"config: tool {name!r} handler type 'script' requires "
                    f"'{where}.handler.command'"
                )
            tool.command = str(command)
            arg_field = handler.get("arg_field")
            if arg_field is None or str(arg_field).strip() == "":
                arg_field = tool.key_field
            if arg_field is None or str(arg_field).strip() == "":
                raise ConfigError(
                    f"config: tool {name!r} handler type 'script' requires "
                    f"'{where}.handler.arg_field'"
                )
            tool.arg_field = str(arg_field).strip()

        tools.append(tool)
    return tools


def tool_arguments(raw: Any) -> dict:
    """Parse a tool call's `arguments` (a JSON string, or already-decoded object)."""
    if isinstance(raw, dict):
        return dict(raw)
    if raw is None:
        return {}
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _lookup_key(tool: Tool, args: dict) -> str:
    key = tool.key_field
    value = args.get(key) if key is not None else None
    if value is None and len(args) == 1:
        value = next(iter(args.values()))
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


async def run_tool_script(tool: Tool, args: dict) -> str:
    """Run `command` with the `arg_field` value as one extra argv entry."""
    try:
        argv = shlex.split(tool.command or "")
    except ValueError as exc:
        return f"ERROR: invalid command {tool.command!r}: {exc}"
    if not argv:
        return "ERROR: empty command"
    value = args.get(tool.arg_field)
    if value is None:
        value = ""
    elif not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    argv.append(value)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        return f"ERROR: {exc}"

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TOOL_TIMEOUT)
    except asyncio.TimeoutError:
        await _kill_process_group(proc)
        return f"ERROR: timed out after {TOOL_TIMEOUT:g}s"

    out = stdout.decode("utf-8", "replace")
    err = stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        return f"ERROR: {err or f'exited with code {proc.returncode}'}"
    return out.strip()


async def execute_tool(tool: Tool | None, name: str, args: dict) -> str:
    """Run one tool call and return the string handed back to the model."""
    if tool is None:
        return f"ERROR: unknown tool {name!r}"
    if tool.handler_type == "echo":
        return json.dumps(args, ensure_ascii=False)
    if tool.handler_type == "static_map":
        value = tool.mapping.get(_lookup_key(tool, args), tool.default)
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return await run_tool_script(tool, args)


# --------------------------------------------------------------------------
# in-context learning setups
# --------------------------------------------------------------------------


def _icl_example(item: Any, where: str) -> IclExample:
    """Validate one `{"input": {...}, "output": "..."}` record."""
    if not isinstance(item, dict):
        raise ConfigError(f"config: {where} must be a mapping with 'input' and 'output'")
    if "input" not in item:
        raise ConfigError(f"config: {where} is missing 'input'")
    if "output" not in item:
        raise ConfigError(f"config: {where} is missing 'output'")
    example_input = item["input"]
    if not isinstance(example_input, dict):
        raise ConfigError(f"config: {where} 'input' must be a mapping")
    output = item["output"]
    if not isinstance(output, str):
        raise ConfigError(f"config: {where} 'output' must be a string")
    return IclExample(input=dict(example_input), output=output)


def load_icl_file(path: str, where: str) -> list[IclExample]:
    """Read a JSONL file of ICL examples; any malformed line is a config error."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise ConfigError(f"config: {where} file not found: {path}") from None
    except IsADirectoryError:
        raise ConfigError(f"config: {where} file is a directory: {path}") from None
    except OSError as exc:
        raise ConfigError(f"config: {where} could not read file {path}: {exc}") from None

    examples: list[IclExample] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"config: {where} file {path} line {lineno} is not valid JSON: {exc}"
            ) from None
        examples.append(_icl_example(item, f"{where} file {path} line {lineno}"))
    return examples


def build_icl(
    raw: Any, args: argparse.Namespace, prefix: str, config_dir: str
) -> IclConfig | None:
    """Parse the optional `icl` section. Returns None when ICL is not configured."""
    if raw is None:
        return None
    section = _require_mapping(raw, f"{prefix}.icl")
    if not section:
        return None

    setups_raw = section.get("setups")
    if setups_raw is None:
        raise ConfigError(f"config: '{prefix}.icl.setups' is required")
    if not isinstance(setups_raw, list):
        raise ConfigError(f"config: '{prefix}.icl.setups' must be a list")
    if not setups_raw:
        raise ConfigError(f"config: '{prefix}.icl.setups' must contain at least one setup")

    setups: list[IclSetup] = []
    for position, item in enumerate(setups_raw):
        where = f"'{prefix}.icl.setups[{position}]'"
        setup_raw = _require_mapping(item, f"{prefix}.icl.setups[{position}]")
        name = setup_raw.get("name")
        if name is None or str(name).strip() == "":
            raise ConfigError(f"config: {where} requires a non-empty 'name'")
        name = str(name)

        has_examples = setup_raw.get("examples") is not None
        has_file = setup_raw.get("file") is not None
        if has_examples == has_file:
            raise ConfigError(
                f"config: ICL setup {name!r} must have exactly one of 'examples' or 'file'"
            )

        if has_examples:
            items = setup_raw["examples"]
            if not isinstance(items, list):
                raise ConfigError(f"config: {where} 'examples' must be a list")
            examples = [
                _icl_example(entry, f"ICL setup {name!r} example {idx}")
                for idx, entry in enumerate(items)
            ]
        else:
            file_path = str(setup_raw["file"]).strip()
            if not file_path:
                raise ConfigError(f"config: {where} 'file' must be a non-empty path")
            if not os.path.isabs(file_path):
                file_path = os.path.join(config_dir, file_path)
            examples = load_icl_file(file_path, f"ICL setup {name!r}")

        setups.append(IclSetup(name=name, examples=examples))

    if getattr(args, "icl_strategy", None):
        strategy = str(args.icl_strategy).strip()
        strategy_label = "--icl-strategy"
    else:
        strategy = str(section.get("strategy", "fixed") or "fixed").strip()
        strategy_label = f"{prefix}.icl.strategy"
    if strategy not in ICL_STRATEGIES:
        raise ConfigError(
            f"config: '{strategy_label}' must be one of {', '.join(ICL_STRATEGIES)}, "
            f"got {strategy!r}"
        )

    if getattr(args, "icl_k", None) is not None:
        k = _as_int(args.icl_k, "--icl-k")
        k_label = "--icl-k"
    elif section.get("k") is not None:
        k = _as_int(section["k"], f"{prefix}.icl.k")
        k_label = f"{prefix}.icl.k"
    else:
        k = None
        k_label = f"{prefix}.icl.k"
    if k is not None and k < 0:
        raise ConfigError(f"config: '{k_label}' must be >= 0, got {k}")

    return IclConfig(setups=setups, strategy=strategy, k=k)


def build_icl_messages(icl: IclConfig, user_template: str, prefix: str) -> None:
    """Render each setup's examples into alternating user/assistant turns."""
    for setup in icl.setups:
        chosen = setup.examples if icl.k is None else setup.examples[: icl.k]
        messages: list[dict] = []
        for index, example in enumerate(chosen):
            try:
                content = user_template.format(**example.input)
            except KeyError as exc:
                missing = exc.args[0] if exc.args else "?"
                raise ConfigError(
                    f"config: '{prefix}.icl' setup {setup.name!r} example {index} is missing "
                    f"field {missing!r} referenced by {prefix}.prompt.user"
                ) from None
            except (IndexError, ValueError) as exc:
                raise ConfigError(
                    f"config: '{prefix}.icl' setup {setup.name!r} example {index}: {exc}"
                ) from None
            messages.append({"role": "user", "content": content})
            messages.append({"role": "assistant", "content": example.output})
        setup.messages = messages


def select_setup_index(config: Config, attempt: int, rng: "random.Random") -> int:
    """Which ICL setup a 0-based attempt uses, per `icl.strategy`."""
    icl = config.icl
    assert icl is not None
    count = len(icl.setups)
    if config.scheme == "greedy" and config.num_solutions > 1:
        # greedy walks setups in declared order, at most once each
        return min(attempt, count - 1)
    if icl.strategy == "fixed":
        return 0
    if icl.strategy == "random":
        return rng.randrange(count)
    return attempt % count


# --------------------------------------------------------------------------
# input
# --------------------------------------------------------------------------


def load_rows(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise ConfigError(f"input file not found: {path}") from None
    except IsADirectoryError:
        raise ConfigError(f"input file is a directory: {path}") from None
    except OSError as exc:
        raise ConfigError(f"could not read input file {path}: {exc}") from None

    rows: list[dict] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"input: row {len(rows)} (line {lineno}) is not valid JSON: {exc}")
        if not isinstance(row, dict):
            raise ConfigError(f"input: row {len(rows)} (line {lineno}) is not a JSON object")
        rows.append(row)
    return rows


def render_template(template: str, row: dict, index: int, what: str) -> str:
    try:
        return template.format(**row)
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "?"
        raise ConfigError(
            f"input: row {index} is missing field {missing!r} referenced by {what}"
        ) from None
    except (IndexError, ValueError) as exc:
        raise ConfigError(f"config: could not render {what}: {exc}") from None


def _require_fields(template: str, row: dict, index: int, what: str) -> None:
    """Check that every {placeholder} except __response__ exists in the row."""
    for name in template_fields(template, what):
        if name == RESPONSE_KEY:
            continue
        if name not in row:
            raise ConfigError(
                f"input: row {index} is missing field {name!r} referenced by {what}"
            )


@dataclass
class RowPrompt:
    """Rendered messages for one input row: the plain prompt plus one ICL variant per setup."""

    base: list[dict]
    variants: list[list[dict]] = field(default_factory=list)

    def messages(self, setup_index: int | None) -> list[dict]:
        if setup_index is None:
            return self.base
        return self.variants[setup_index]


def prepare_prompts(config: Config, rows: list[dict]) -> list[RowPrompt]:
    """Render every prompt up front so template/field errors surface before any request."""
    messages_per_row: list[RowPrompt] = []
    ev = config.evaluation
    answer_field = ev.answer_field if ev else None
    for index, row in enumerate(rows):
        prefix: list[dict] = []
        if config.system_template is not None:
            prefix.append(
                {
                    "role": "system",
                    "content": render_template(
                        config.system_template, row, index, "prompt.system"
                    ),
                }
            )
        user_message = {
            "role": "user",
            "content": render_template(config.user_template, row, index, "prompt.user"),
        }
        messages = prefix + [user_message]
        variants: list[list[dict]] = []
        if config.icl is not None:
            # ICL examples sit between the system message and the final user turn
            variants = [
                prefix + setup.messages + [user_message] for setup in config.icl.setups
            ]
        if answer_field and answer_field not in row:
            raise ConfigError(
                f"input: row {index} is missing field {answer_field!r} "
                f"required by evaluation.answer_field"
            )
        if ev is not None and ev.type == "script":
            _require_fields(ev.command_template, row, index, "evaluation.command_template")
        if ev is not None and ev.type == "llm_judge":
            _require_fields(ev.judge_user, row, index, "evaluation.judge_prompt.user")
            if ev.judge_system is not None:
                _require_fields(ev.judge_system, row, index, "evaluation.judge_prompt.system")
        messages_per_row.append(RowPrompt(base=messages, variants=variants))
    return messages_per_row


# --------------------------------------------------------------------------
# extraction + evaluation
# --------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d*\.\d+|-?\d+")
_LETTER_RE = re.compile(r"(?<![A-Za-z0-9])([A-D])(?![A-Za-z0-9])")


def extract_value(text: str, method: str) -> str | None:
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
        if match is None:
            return None
        return match.group(0).replace(",", "")
    if method == "letter":
        match = _LETTER_RE.search(text)
        if match is None:
            return None
        return match.group(1)
    return text.strip()


def _normalize(value: str) -> str:
    value = value.strip()
    value = value.replace(",", "").replace("$", "").replace("%", "")
    value = value.strip().rstrip(".")
    return value.strip()


def values_match(extracted: str | None, expected: Any) -> bool:
    if extracted is None or expected is None:
        return False
    expected_str = expected if isinstance(expected, str) else str(expected)
    if extracted.strip() == expected_str.strip():
        return True
    left, right = _normalize(extracted), _normalize(expected_str)
    if left == right:
        return True
    try:
        lnum, rnum = float(left), float(right)
    except (TypeError, ValueError):
        return False
    if math.isnan(lnum) or math.isnan(rnum):
        return False
    return math.isclose(lnum, rnum, rel_tol=1e-9, abs_tol=1e-9)


def parse_number(value: str | None) -> float | int | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


@dataclass
class EvalOutcome:
    passed: bool | None
    extracted: str | None = None
    judge_score: float | int | None = None
    judge_meta: dict | None = None


def evaluate_local(config: Config, text: str, row: dict) -> tuple[bool | None, str | None]:
    """exact_match / contains / regex: (passed, extracted_answer)."""
    ev = config.evaluation
    if ev is None:
        return None, None

    if ev.type == "regex":
        match = ev.regex.search(text) if ev.regex is not None else None
        if match is not None:
            extracted = match.group(1) if match.groups() else match.group(0)
            return True, extracted
        return False, extract_value(text, ev.extract)

    extracted = extract_value(text, ev.extract)
    expected = row.get(ev.answer_field) if ev.answer_field else None

    if ev.type == "contains":
        expected_str = "" if expected is None else str(expected)
        return (expected_str in text), extracted

    return values_match(extracted, expected), extracted


def render_command(ev: Evaluation, text: str, row: dict, index: int) -> str:
    """Render the shell command, substituting __response__ even inside row fields."""
    values = dict(row)
    values[RESPONSE_KEY] = text
    command = render_template(
        ev.command_template, values, index, "evaluation.command_template"
    )
    if RESPONSE_PLACEHOLDER in command:
        command = command.replace(RESPONSE_PLACEHOLDER, text)
    return command


async def run_script_eval(ev: Evaluation, text: str, row: dict, index: int) -> bool:
    try:
        command = render_command(ev, text, row, index)
    except ConfigError:
        return False

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group, so a timeout can kill grandchildren
        )
    except OSError:
        return False

    try:
        # stdout/stderr are captured but deliberately never written to the output
        await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT)
    except asyncio.TimeoutError:
        await _kill_process_group(proc)
        return False

    return proc.returncode == ev.success_exit_code


async def _kill_process_group(proc: Any) -> None:
    """Kill the command and anything it spawned; a lingering grandchild would
    otherwise hold the captured pipes open past the timeout."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except (asyncio.TimeoutError, ProcessLookupError, OSError):
        pass


async def run_judge_eval(
    client: httpx.AsyncClient,
    config: Config,
    text: str,
    row: dict,
    index: int,
    ctx: "RunContext",
) -> EvalOutcome:
    ev = config.evaluation
    values = dict(row)
    values[RESPONSE_KEY] = text

    try:
        messages: list[dict] = []
        if ev.judge_system is not None:
            messages.append(
                {
                    "role": "system",
                    "content": render_template(
                        ev.judge_system, values, index, "evaluation.judge_prompt.system"
                    ),
                }
            )
        messages.append(
            {
                "role": "user",
                "content": render_template(
                    ev.judge_user, values, index, "evaluation.judge_prompt.user"
                ),
            }
        )
    except ConfigError:
        return EvalOutcome(False, None, None, _empty_meta(ev.model or config.model, 0))

    result = await call_api(
        client,
        config.api_url,
        ev.model or config.model,
        messages,
        ev.judge_temperature,
        ev.judge_max_tokens or config.max_tokens,
        ctx,
        api_type=config.api_type,
        chat_template=config.chat_template,
    )
    if not result.ok:
        return EvalOutcome(False, None, None, result.meta)

    extracted = extract_value(result.content, ev.extract)
    score = parse_number(extracted)
    if score is None:
        return EvalOutcome(False, extracted, None, result.meta)
    return EvalOutcome(score >= ev.threshold, extracted, score, result.meta)


async def evaluate_response(
    client: httpx.AsyncClient,
    config: Config,
    text: str,
    row: dict,
    index: int,
    ctx: "RunContext",
) -> EvalOutcome:
    ev = config.evaluation
    if ev is None:
        return EvalOutcome(None, None)
    if ev.type == "script":
        passed = await run_script_eval(ev, text, row, index)
        extracted = extract_value(text, ev.extract) if ev.extract_given else None
        return EvalOutcome(passed, extracted)
    if ev.type == "llm_judge":
        return await run_judge_eval(client, config, text, row, index, ctx)
    passed, extracted = evaluate_local(config, text, row)
    return EvalOutcome(passed, extracted)


# --------------------------------------------------------------------------
# structured output validation (JSON Schema draft 7 subset)
# --------------------------------------------------------------------------


def _json_type_of(value: Any) -> str:
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


def _type_ok(value: Any, expected: str) -> bool:
    actual = _json_type_of(value)
    if expected == "number":
        return actual in ("number", "integer")
    if expected == "integer":
        return actual == "integer" or (actual == "number" and float(value).is_integer())
    return actual == expected


def _at(path: str) -> str:
    return f" at '{path}'" if path else ""


def validate_schema(value: Any, schema: Any, path: str = "") -> str | None:
    """Validate `value`; returns a human-readable message, or None when valid."""
    if not isinstance(schema, dict):
        return None

    expected = schema.get("type")
    if expected is not None:
        options = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, str(option)) for option in options):
            names = " or ".join(f"'{option}'" for option in options)
            return (
                f"Expected type {names}{_at(path)}, got '{_json_type_of(value)}'"
            )

    if "enum" in schema and isinstance(schema["enum"], list):
        if not any(value == option for option in schema["enum"]):
            return f"Value{_at(path) or ' '}must be one of {json.dumps(schema['enum'])}"

    if isinstance(value, dict):
        required = schema.get("required")
        if isinstance(required, list):
            for name in required:
                if str(name) not in value:
                    return f"Missing required field: {name}"
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, sub in properties.items():
                if name in value:
                    child = f"{path}.{name}" if path else str(name)
                    message = validate_schema(value[name], sub, child)
                    if message is not None:
                        return message

    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, list):
            for position, sub in enumerate(items):
                if position < len(value):
                    message = validate_schema(value[position], sub, f"{path}[{position}]")
                    if message is not None:
                        return message
        elif isinstance(items, dict):
            for position, item in enumerate(value):
                message = validate_schema(item, items, f"{path}[{position}]")
                if message is not None:
                    return message

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and not isinstance(minimum, bool):
            if value < minimum:
                return f"Value {value}{_at(path)} is less than minimum {minimum}"
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and not isinstance(maximum, bool):
            if value > maximum:
                return f"Value {value}{_at(path)} is greater than maximum {maximum}"

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and not isinstance(min_length, bool):
            if len(value) < min_length:
                return (
                    f"String{_at(path)} is shorter than minLength {min_length}"
                )
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and not isinstance(max_length, bool):
            if len(value) > max_length:
                return f"String{_at(path)} is longer than maxLength {max_length}"
        pattern = schema.get("pattern")
        if pattern is not None:
            try:
                compiled = re.compile(str(pattern))
            except re.error:
                compiled = None
            if compiled is not None and compiled.search(value) is None:
                return f"String{_at(path)} does not match pattern {str(pattern)!r}"

    return None


@dataclass
class SchemaOutcome:
    """The result of parsing + validating one response against `output_schema`."""

    valid: bool
    value: Any = None
    error: str | None = None


def check_output_schema(schema: dict | None, text: str | None) -> SchemaOutcome:
    """Parse `text` as JSON and validate it; invalid JSON is a schema failure."""
    if schema is None:
        return SchemaOutcome(True, text)
    if text is None:
        return SchemaOutcome(False, None, "No response content to validate")
    try:
        value = json.loads(strip_json_fence(text))
    except (json.JSONDecodeError, ValueError) as exc:
        return SchemaOutcome(False, None, f"Invalid JSON: {exc}")
    message = validate_schema(value, schema)
    if message is not None:
        return SchemaOutcome(False, None, message)
    return SchemaOutcome(True, value)


def strip_json_fence(text: str) -> str:
    """Tolerate ```json fenced blocks around an otherwise plain JSON reply."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped[3:]
    if body[:4].lower() == "json":
        body = body[4:]
    if body.endswith("```"):
        body = body[:-3]
    return body.strip()


# --------------------------------------------------------------------------
# chat templates (completions mode)
# --------------------------------------------------------------------------


def _content(message: dict) -> str:
    value = message.get("content")
    return "" if value is None else str(value)


def _role(message: dict) -> str:
    role = message.get("role")
    return "user" if role is None else str(role)


def render_chatml(messages: list[dict]) -> str:
    parts = [f"<|im_start|>{_role(m)}\n{_content(m)}<|im_end|>\n" for m in messages]
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


def render_llama3(messages: list[dict]) -> str:
    parts = ["<|begin_of_text|>"]
    for message in messages:
        parts.append(
            f"<|start_header_id|>{_role(message)}<|end_header_id|>\n\n"
            f"{_content(message)}<|eot_id|>"
        )
    parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return "".join(parts)


def render_zephyr(messages: list[dict]) -> str:
    parts = [f"<|{_role(m)}|>\n{_content(m)}</s>\n" for m in messages]
    parts.append("<|assistant|>\n")
    return "".join(parts)


def render_mistral(messages: list[dict]) -> str:
    """Mistral has no system role: system text is folded into the next [INST] block."""
    parts: list[str] = []
    pending: list[str] = []
    for message in messages:
        role = _role(message)
        content = _content(message)
        if role == "system":
            pending.append(content)
            continue
        if role == "assistant":
            parts.append(f"{content}</s>")
            continue
        # user and tool turns both become instruction blocks
        if pending:
            content = "\n\n".join(pending + [content])
            pending = []
        parts.append(f"[INST] {content} [/INST]")
    if pending:
        parts.append(f"[INST] {chr(10).join(pending)} [/INST]")
    return "".join(parts)


TEMPLATE_RENDERERS = {
    "chatml": render_chatml,
    "llama3": render_llama3,
    "mistral": render_mistral,
    "zephyr": render_zephyr,
}


def render_chat_prompt(messages: list[dict], template: str) -> str:
    """Flatten a conversation into one prompt string for /v1/completions."""
    renderer = TEMPLATE_RENDERERS.get(template, render_chatml)
    return renderer(messages)


def tools_prompt_block(tools: list[Tool]) -> str:
    """Tool declarations + call protocol, injected into the prompt in completions mode."""
    lines = ["You have access to the following tools:", ""]
    for tool in tools:
        lines.append(
            json.dumps(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters or {"type": "object", "properties": {}},
                },
                ensure_ascii=False,
            )
        )
    lines += [
        "",
        "To call a tool, reply with a block of exactly this form:",
        "<tool_call>",
        '{"name": "<tool name>", "arguments": {<arguments as JSON>}}',
        "</tool_call>",
        "",
        "You may emit several <tool_call> blocks in one reply. "
        "When you are done calling tools, reply with the final answer as plain text "
        "and no <tool_call> block.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# scheduling: rate limits, cost budget, progress
# --------------------------------------------------------------------------


def count_words(text: str) -> int:
    return len(text.split())


def messages_text(messages: list[dict], api_type: str = "chat", chat_template: str = "chatml") -> str:
    """The text actually sent for a request, used for token estimates."""
    if api_type == "completions":
        return render_chat_prompt(messages, chat_template)
    return "\n".join(_content(message) for message in messages)


def estimate_prompt_tokens(
    messages: list[dict], api_type: str = "chat", chat_template: str = "chatml"
) -> int:
    """Word count of the rendered messages at 1 token ~= 0.75 words, rounded up."""
    words = count_words(messages_text(messages, api_type, chat_template))
    return int(math.ceil(words / WORDS_PER_TOKEN))


@dataclass
class TokenReservation:
    """One entry in the TPM window: an estimate until the real usage lands."""

    at: float
    tokens: int


class RateLimiter:
    """Sliding 60s RPM and TPM windows plus a hard in-flight cap."""

    def __init__(self, limits: RateLimits) -> None:
        self.rpm = limits.rpm
        self.tpm = limits.tpm
        self.max_concurrent = limits.max_concurrent
        self._requests: deque[float] = deque()
        self._tokens: deque[TokenReservation] = deque()
        self._lock = asyncio.Lock()
        self._semaphore = (
            asyncio.Semaphore(self.max_concurrent) if self.max_concurrent else None
        )

    # -- concurrency ------------------------------------------------------
    async def acquire_slot(self) -> None:
        if self._semaphore is not None:
            await self._semaphore.acquire()

    def release_slot(self) -> None:
        if self._semaphore is not None:
            self._semaphore.release()

    def slot(self, held: bool = False) -> "_SlotGuard":
        """Async context manager for one in-flight slot (`held`: already owned)."""
        return _SlotGuard(self, held)

    # -- windows ----------------------------------------------------------
    def _prune(self, now: float) -> None:
        cutoff = now - RATE_WINDOW
        while self._requests and self._requests[0] <= cutoff:
            self._requests.popleft()
        while self._tokens and self._tokens[0].at <= cutoff:
            self._tokens.popleft()

    def _used_tokens(self) -> int:
        return sum(entry.tokens for entry in self._tokens)

    async def admit(self, reserve: int) -> TokenReservation | None:
        """Wait until both windows have room, then book this request."""
        if not self.rpm and not self.tpm:
            return None
        while True:
            async with self._lock:
                now = time.monotonic()
                self._prune(now)
                request_wait = 0.0
                token_wait = 0.0
                if self.rpm and len(self._requests) >= self.rpm:
                    request_wait = self._requests[0] + RATE_WINDOW - now
                if self.tpm and self._tokens:
                    if self._used_tokens() + reserve > self.tpm:
                        token_wait = self._tokens[0].at + RATE_WINDOW - now
                wait = max(request_wait, token_wait)
                if wait <= 0:
                    if self.rpm:
                        self._requests.append(now)
                    if self.tpm:
                        entry = TokenReservation(now, max(0, reserve))
                        self._tokens.append(entry)
                        return entry
                    return None
            if token_wait > 0:
                # poll: usage reported by a finished request can free budget early
                wait = min(wait, 0.05)
            await asyncio.sleep(min(max(wait, 0.001), RATE_WINDOW) + 0.002)

    def record_usage(self, reservation: TokenReservation | None, tokens: int | None) -> None:
        """Replace a reservation's estimate with the usage the API reported."""
        if reservation is None or tokens is None:
            return
        reservation.tokens = max(0, tokens)


class _SlotGuard:
    def __init__(self, limiter: RateLimiter, held: bool) -> None:
        self._limiter = limiter
        self._held = held

    async def __aenter__(self) -> "_SlotGuard":
        if not self._held:
            await self._limiter.acquire_slot()
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        if not self._held:
            self._limiter.release_slot()
        return False


class CostTracker:
    """Running spend over every task, task by task prices."""

    def __init__(self) -> None:
        self.prompt = 0.0
        self.completion = 0.0
        self.stopped = False

    @property
    def total(self) -> float:
        return self.prompt + self.completion

    def add(self, cost: CostConfig, prompt_tokens: int, completion_tokens: int) -> None:
        if not cost.configured:
            return
        prompt_cost, completion_cost = cost.call_cost(prompt_tokens, completion_tokens)
        self.prompt += prompt_cost
        self.completion += completion_cost

    def exhausted(self, budget: float | None) -> bool:
        return budget is not None and self.total >= budget


@dataclass
class RunContext:
    """Everything one task's requests need beyond the HTTP client."""

    config: Config
    counter: Counter
    limiter: RateLimiter
    tracker: CostTracker

    def check_budget(self) -> None:
        if self.tracker.exhausted(self.config.cost.budget):
            self.tracker.stopped = True
            raise BudgetStop(f"cost budget {self.config.cost.budget} reached")

    @property
    def budget_spent(self) -> bool:
        return self.tracker.exhausted(self.config.cost.budget)

    def record_cost(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.tracker.add(self.config.cost, prompt_tokens, completion_tokens)


class Progress:
    """`--progress`: one stderr line every 5s or every 10% of the inputs."""

    INTERVAL = 5.0

    def __init__(
        self,
        total: int,
        counter: Counter,
        tracker: CostTracker,
        show_eval: bool,
        show_cost: bool,
        stream: Any = None,
    ) -> None:
        self.total = total
        self.counter = counter
        self.tracker = tracker
        self.show_eval = show_eval
        self.show_cost = show_cost
        self.stream = stream if stream is not None else sys.stderr
        self.done = 0
        self.passed = 0
        self.failed = 0
        self.started = time.monotonic()
        self.last_emit = self.started
        self.last_done = 0
        self.step = max(1, total // 10) if total else 1

    def row_done(self, record: dict | None) -> None:
        self.done += 1
        if record is not None:
            if record_passed(record):
                self.passed += 1
            else:
                self.failed += 1
        now = time.monotonic()
        if now - self.last_emit >= self.INTERVAL or self.done - self.last_done >= self.step:
            self.emit(now)

    def emit(self, now: float | None = None, final: bool = False) -> None:
        if final and self.done == self.last_done and self.last_emit > self.started:
            return  # the last row already produced this line
        now = time.monotonic() if now is None else now
        self.last_emit = now
        self.last_done = self.done
        elapsed = max(1e-9, now - self.started)
        percent = int(self.done * 100 / self.total) if self.total else 100
        rpm = self.counter.api_calls / elapsed * 60.0
        remaining = max(0, self.total - self.done)
        eta = int(round(remaining * elapsed / self.done)) if self.done else 0
        parts = [f"[{self.done}/{self.total}] {percent}% complete"]
        if self.show_eval:
            parts.append(f"{self.passed} passed, {self.failed} failed")
        parts.append(f"{rpm:.1f} rpm")
        if self.show_cost:
            parts.append(f"${self.tracker.total:.2f} spent")
        parts.append(f"ETA: {eta}s")
        try:
            self.stream.write(" | ".join(parts) + "\n")
            self.stream.flush()
        except (OSError, ValueError):
            pass


# --------------------------------------------------------------------------
# API client
# --------------------------------------------------------------------------


@dataclass
class CallResult:
    ok: bool
    content: str | None
    meta: dict
    api_calls: int
    error: str | None = None
    tool_calls: list = field(default_factory=list)  # raw OpenAI tool_calls, chat mode only


class Counter:
    """Counts API calls; a per-task counter propagates to the global one."""

    def __init__(self, parent: "Counter | None" = None) -> None:
        self.parent = parent
        self.api_calls = 0
        self.first_request_at: float | None = None
        self.last_response_at: float | None = None

    def mark_request(self, at: float) -> None:
        self.api_calls += 1
        if self.first_request_at is None or at < self.first_request_at:
            self.first_request_at = at
        if self.parent is not None:
            self.parent.mark_request(at)

    def mark_response(self, at: float) -> None:
        if self.last_response_at is None or at > self.last_response_at:
            self.last_response_at = at
        if self.parent is not None:
            self.parent.mark_response(at)


def _empty_meta(model: str, latency_ms: int) -> dict:
    return {
        "model": model,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latency_ms": latency_ms,
        "finish_reason": None,
    }


async def call_api(
    client: httpx.AsyncClient,
    api_url: str,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    ctx: "RunContext",
    tools: list[dict] | None = None,
    api_type: str = "chat",
    chat_template: str = "chatml",
    slot_held: bool = False,
) -> CallResult:
    """One logical API call, retrying HTTP 5xx / transport failures.

    Every HTTP attempt passes the task's limiter (RPM, TPM and the in-flight
    cap) and its usage is added to the run's cost. `slot_held` is set by the
    agentic loop, which owns one concurrency slot for its whole lifetime.
    """
    counter = ctx.counter
    if api_type == "completions":
        url = f"{api_url}/v1/completions"
        payload = {
            "model": model,
            "prompt": render_chat_prompt(messages, chat_template),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    else:
        url = f"{api_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

    calls = 0
    last_error = "request failed"
    total_latency_ms = 0
    reserve = estimate_prompt_tokens(messages, api_type, chat_template) + max_tokens

    for attempt in range(MAX_RETRIES + 1):
        ctx.check_budget()
        async with ctx.limiter.slot(slot_held):
            # re-checked after queueing: the budget may have run out while waiting
            ctx.check_budget()
            reservation = await ctx.limiter.admit(reserve)
            ctx.check_budget()
            started = time.perf_counter()
            counter.mark_request(started)
            calls += 1
            try:
                response = await client.post(url, json=payload)
                elapsed = time.perf_counter() - started
                counter.mark_response(time.perf_counter())
                latency_ms = int(round(elapsed * 1000))
                total_latency_ms += latency_ms

                if response.status_code >= 500:
                    last_error = f"HTTP {response.status_code}"
                elif response.status_code >= 400:
                    return CallResult(
                        False,
                        None,
                        _empty_meta(model, latency_ms),
                        calls,
                        f"HTTP {response.status_code}",
                    )
                else:
                    try:
                        body = response.json()
                    except ValueError as exc:
                        return CallResult(
                            False,
                            None,
                            _empty_meta(model, latency_ms),
                            calls,
                            f"invalid JSON response: {exc}",
                        )
                    parsed = parse_completion(body, model, latency_ms)
                    if parsed is None:
                        return CallResult(
                            False,
                            None,
                            _empty_meta(model, latency_ms),
                            calls,
                            "malformed completion response",
                        )
                    content, meta, tool_calls = parsed
                    prompt_tokens = meta.get("prompt_tokens") or 0
                    completion_tokens = meta.get("completion_tokens") or 0
                    ctx.limiter.record_usage(reservation, prompt_tokens + completion_tokens)
                    ctx.record_cost(prompt_tokens, completion_tokens)
                    return CallResult(True, content, meta, calls, tool_calls=tool_calls)
            except (httpx.HTTPError, OSError) as exc:
                elapsed = time.perf_counter() - started
                counter.mark_response(time.perf_counter())
                total_latency_ms += int(round(elapsed * 1000))
                last_error = f"{type(exc).__name__}: {exc}"

        if attempt < MAX_RETRIES:
            await asyncio.sleep(min(0.25 * (2**attempt), 2.0))

    return CallResult(False, None, _empty_meta(model, total_latency_ms), calls, last_error)


def parse_completion(
    body: Any, model: str, latency_ms: int
) -> tuple[str | None, dict, list] | None:
    """Returns (text, meta, tool_calls); None when the response is unusable."""
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    message = choice.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        content = choice.get("text")

    tool_calls: list = []
    if isinstance(message, dict):
        raw_calls = message.get("tool_calls")
        if isinstance(raw_calls, list):
            tool_calls = [call for call in raw_calls if isinstance(call, dict)]

    if content is None and not tool_calls:
        return None

    usage = body.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    def _tok(key: str) -> int:
        value = usage.get(key)
        return int(value) if isinstance(value, (int, float)) else 0

    meta = {
        "model": body.get("model") or model,
        "prompt_tokens": _tok("prompt_tokens"),
        "completion_tokens": _tok("completion_tokens"),
        "total_tokens": _tok("total_tokens"),
        "latency_ms": latency_ms,
        "finish_reason": choice.get("finish_reason"),
    }
    text = None if content is None else str(content)
    return text, meta, tool_calls


# --------------------------------------------------------------------------
# agentic loop
# --------------------------------------------------------------------------


@dataclass
class ToolInvocation:
    """One tool call requested by the model."""

    id: str
    name: str
    args: dict
    raw: dict | None = None  # the assistant message entry, chat mode only


@dataclass
class AgenticLoop:
    """The outcome of one agentic run (one logical solution attempt)."""

    ok: bool
    content: str | None
    iterations: int
    tool_calls: list[dict]
    iterations_detail: list[dict]
    finish_reason: str | None
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def meta(self) -> dict:
        return {
            "total_prompt_tokens": self.prompt_tokens,
            "total_completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "iterations_detail": self.iterations_detail,
        }

    def single_meta(self) -> dict:
        """Part 1 shaped meta: the loop's aggregates plus per-iteration detail."""
        meta = self.meta()
        meta.pop("iterations", None)
        meta.pop("tool_calls", None)
        return meta


def parse_text_tool_calls(text: str | None) -> list[ToolInvocation]:
    """Pull `<tool_call>{...}</tool_call>` blocks out of a completions response."""
    if not text:
        return []
    invocations: list[ToolInvocation] = []
    for position, block in enumerate(TOOL_CALL_RE.findall(text)):
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        name = parsed.get("name")
        if name is None or str(name).strip() == "":
            continue
        args = tool_arguments(parsed.get("arguments", parsed.get("parameters")))
        invocations.append(
            ToolInvocation(id=f"call_{position + 1}", name=str(name), args=args)
        )
    return invocations


def parse_message_tool_calls(raw_calls: list) -> list[ToolInvocation]:
    """Normalise OpenAI `tool_calls` entries from a chat response."""
    invocations: list[ToolInvocation] = []
    for position, call in enumerate(raw_calls):
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if name is None or str(name).strip() == "":
            continue
        args = tool_arguments(function.get("arguments"))
        call_id = call.get("id") or f"call_{position + 1}"
        invocations.append(
            ToolInvocation(id=str(call_id), name=str(name), args=args, raw=call)
        )
    return invocations


def agentic_conversation(config: Config, messages: list[dict]) -> list[dict]:
    """Copy the row's prompt; completions mode also gets the tool protocol inlined."""
    conversation = [dict(message) for message in messages]
    if config.api_type != "completions" or not config.tools:
        return conversation
    block = tools_prompt_block(config.tools)
    if conversation and conversation[0].get("role") == "system":
        existing = _content(conversation[0])
        conversation[0] = {
            "role": "system",
            "content": f"{existing}\n\n{block}" if existing else block,
        }
    else:
        conversation.insert(0, {"role": "system", "content": block})
    return conversation


def append_assistant_turn(
    config: Config,
    conversation: list[dict],
    result: CallResult,
    invocations: list[ToolInvocation],
) -> None:
    if config.api_type == "completions":
        conversation.append({"role": "assistant", "content": result.content or ""})
        return
    raw = [inv.raw for inv in invocations if inv.raw is not None]
    if not raw:
        raw = [
            {
                "id": inv.id,
                "type": "function",
                "function": {"name": inv.name, "arguments": json.dumps(inv.args)},
            }
            for inv in invocations
        ]
    conversation.append(
        {"role": "assistant", "content": result.content, "tool_calls": raw}
    )


def append_tool_result(
    config: Config, conversation: list[dict], invocation: ToolInvocation, output: str
) -> None:
    if config.api_type == "completions":
        # the template renders this with its own tool-role markers
        conversation.append(
            {"role": "tool", "name": invocation.name, "content": output}
        )
        return
    conversation.append(
        {
            "role": "tool",
            "tool_call_id": invocation.id,
            "name": invocation.name,
            "content": output,
        }
    )


async def run_agentic_loop(
    client: httpx.AsyncClient,
    config: Config,
    messages: list[dict],
    ctx: "RunContext",
) -> AgenticLoop:
    """Call the API in a loop, running tools until the model answers in plain text.

    The loop holds one concurrency slot for its entire lifetime; each request it
    makes still counts toward RPM, TPM and cost.
    """
    conversation = agentic_conversation(config, messages)
    tools_payload = (
        [tool.definition() for tool in config.tools]
        if config.tools and config.api_type != "completions"
        else None
    )
    by_name = {tool.name: tool for tool in config.tools}

    details: list[dict] = []
    calls_log: list[dict] = []
    prompt_tokens = completion_tokens = total_tokens = 0
    iterations = 0
    content: str | None = None
    finish_reason: str | None = None
    ok = False
    started = time.perf_counter()

    async with ctx.limiter.slot():
        while iterations < config.max_iterations:
            result = await call_api(
                client,
                config.api_url,
                config.model,
                conversation,
                config.temperature,
                config.max_tokens,
                ctx,
                tools=tools_payload,
                slot_held=True,
                api_type=config.api_type,
                chat_template=config.chat_template,
            )
            iterations += 1
            meta = result.meta
            detail = {
                "prompt_tokens": meta.get("prompt_tokens") or 0,
                "completion_tokens": meta.get("completion_tokens") or 0,
                "total_tokens": meta.get("total_tokens") or 0,
                "latency_ms": meta.get("latency_ms") or 0,
                "finish_reason": meta.get("finish_reason"),
            }
            details.append(detail)
            prompt_tokens += detail["prompt_tokens"]
            completion_tokens += detail["completion_tokens"]
            total_tokens += detail["total_tokens"]

            if not result.ok:
                finish_reason = None
                break

            if config.api_type == "completions":
                invocations = parse_text_tool_calls(result.content)
            else:
                invocations = parse_message_tool_calls(result.tool_calls)

            if invocations:
                detail["finish_reason"] = "tool_calls"
                append_assistant_turn(config, conversation, result, invocations)
                for invocation in invocations:
                    output = await execute_tool(
                        by_name.get(invocation.name), invocation.name, invocation.args
                    )
                    calls_log.append(
                        {
                            "iteration": iterations,
                            "tool": invocation.name,
                            "args": invocation.args,
                            "result": output,
                        }
                    )
                    append_tool_result(config, conversation, invocation, output)
                continue

            content = result.content if result.content is not None else ""
            finish_reason = "stop"
            ok = True
            break
        else:
            finish_reason = "max_iterations"

    latency_ms = int(round((time.perf_counter() - started) * 1000))
    return AgenticLoop(
        ok=ok,
        content=content,
        iterations=iterations,
        tool_calls=calls_log,
        iterations_detail=details,
        finish_reason=finish_reason,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


# --------------------------------------------------------------------------
# row processing
# --------------------------------------------------------------------------


async def process_row(
    client: httpx.AsyncClient,
    config: Config,
    row: dict,
    prompt: RowPrompt,
    ctx: "RunContext",
    index: int,
) -> dict:
    """One input row -> one output record."""
    if config.list_format:
        return await process_row_multi(client, config, row, prompt, ctx, index)
    if config.is_agentic:
        return await process_row_agentic(client, config, row, prompt.base, ctx, index)
    return await process_row_single(client, config, row, prompt.base, ctx, index)


async def process_row_agentic(
    client: httpx.AsyncClient,
    config: Config,
    row: dict,
    messages: list[dict],
    ctx: "RunContext",
    index: int,
) -> dict:
    """One agentic loop: tool calls until a final text answer (or max_iterations)."""
    is_judge = config.evaluation is not None and config.evaluation.type == "llm_judge"
    has_schema = config.output_schema is not None
    loop = await run_agentic_loop(client, config, messages, ctx)
    meta = loop.single_meta()

    content = loop.content
    value: Any = content
    passed: bool | None = None if config.evaluation is None else False
    extracted: str | None = None
    judge_score: float | int | None = None
    schema = check_output_schema(config.output_schema, content) if has_schema else None

    if has_schema and not schema.valid:
        content = None
        value = None
        passed = False
    elif content is not None:
        if has_schema:
            value = schema.value
        outcome = await evaluate_response(client, config, content, row, index, ctx)
        if outcome.judge_meta is not None:
            meta["judge_meta"] = outcome.judge_meta
        passed = outcome.passed
        extracted = outcome.extracted
        judge_score = outcome.judge_score
        if config.evaluation is None and has_schema:
            passed = True

    output = None if content is None else {config.output_field: value}
    result_block: dict[str, Any] = {
        "passed": passed,
        "extracted_answer": extracted if output is not None else None,
        "attempts": 1,
        "iterations": loop.iterations,
        "tool_calls": loop.tool_calls,
    }
    if is_judge:
        result_block["judge_score"] = judge_score if output is not None else None
    if has_schema:
        result_block["schema_valid"] = bool(schema.valid)
        if not schema.valid:
            result_block["schema_error"] = schema.error

    return {
        "input": row,
        "output": output,
        "result": result_block,
        "meta": meta,
    }


async def process_row_single(
    client: httpx.AsyncClient,
    config: Config,
    row: dict,
    messages: list[dict],
    ctx: "RunContext",
    index: int,
) -> dict:
    """Part 1/2 behaviour: one solution, object-shaped output and meta."""
    metas: list[dict] = []
    attempts = 0
    passed: bool | None = None
    extracted: str | None = None
    judge_score: float | int | None = None
    content: str | None = None
    value: Any = None

    has_eval = config.evaluation is not None
    has_schema = config.output_schema is not None
    is_judge = has_eval and config.evaluation.type == "llm_judge"
    schema_valid = False if has_schema else None
    schema_error: str | None = None
    max_attempts = config.n if config.scheme == "rejection" else 1

    try:
        while attempts < max_attempts:
            attempts += 1
            result = await call_api(
                client,
                config.api_url,
                config.model,
                messages,
                config.temperature,
                config.max_tokens,
                ctx,
                api_type=config.api_type,
                chat_template=config.chat_template,
            )
            metas.append(result.meta)
            if not result.ok or result.content is None:
                # a content-less reply (e.g. bare tool_calls) is not a usable generation
                content = None
                value = None
                passed = False if has_eval or has_schema else None
                extracted = None
                judge_score = None
                if has_schema:
                    schema_valid = False
                    schema_error = "No response content to validate"
                break

            if has_schema:
                # structured output is validated before any other evaluation
                schema = check_output_schema(config.output_schema, result.content)
                schema_valid = schema.valid
                schema_error = schema.error
                if not schema.valid:
                    content = None
                    value = None
                    extracted = None
                    judge_score = None
                    passed = False
                    if config.scheme == "rejection":
                        continue  # a schema failure is a failed attempt
                    break
                value = schema.value
            else:
                value = result.content

            outcome = await evaluate_response(client, config, result.content, row, index, ctx)
            if outcome.judge_meta is not None:
                result.meta["judge_meta"] = outcome.judge_meta
            passed = outcome.passed
            extracted = outcome.extracted
            judge_score = outcome.judge_score
            if not has_eval and has_schema:
                passed = True
            content = result.content
            if config.scheme != "rejection" or passed:
                break
            # rejection: this attempt failed evaluation, drop it and try again
            content = None
            value = None
            extracted = None
            judge_score = None
    except BudgetStop:
        if content is None:
            raise
        # the interrupted attempt never produced a meta entry; don't count it
        attempts = len(metas)

    if content is None and config.scheme == "rejection":
        passed = False
        extracted = None
        judge_score = None

    output = None if content is None else {config.output_field: value}
    meta_out: Any = metas[0] if len(metas) == 1 else metas
    if not metas:
        meta_out = None

    result_block: dict[str, Any] = {
        "passed": passed,
        "extracted_answer": extracted if output is not None else None,
        "attempts": attempts,
    }
    if is_judge:
        result_block["judge_score"] = judge_score if output is not None else None
    if has_schema:
        result_block["schema_valid"] = bool(schema_valid)
        if not schema_valid:
            result_block["schema_error"] = schema_error

    return {
        "input": row,
        "output": output,
        "result": result_block,
        "meta": meta_out,
    }


def _attempt_budget(config: Config) -> int:
    """How many generation attempts a row may make at most."""
    if config.scheme == "greedy":
        if config.icl is not None and config.num_solutions > 1:
            # one deterministic shot per setup: at most one solution each
            return len(config.icl.setups)
        return 1
    if config.scheme in ("sample", "agentic"):
        # one independent generation (for agentic: one whole loop) per solution
        return config.num_solutions
    return config.max_attempts or (3 * config.num_solutions)


async def process_row_multi(
    client: httpx.AsyncClient,
    config: Config,
    row: dict,
    prompt: RowPrompt,
    ctx: "RunContext",
    index: int,
) -> dict:
    """Part 3 behaviour: a list of solutions, one meta entry per attempt."""
    rng = random.Random()
    has_eval = config.evaluation is not None
    has_schema = config.output_schema is not None
    budget = _attempt_budget(config)
    gated = config.scheme == "rejection"  # only rejection drops failing generations

    metas: list[dict] = []
    outputs: list[dict] = []
    attempts = 0
    passed_count = 0
    accepted = 0

    try:
        while attempts < budget:
            if gated:
                if accepted >= config.num_solutions:
                    break
            elif len(outputs) >= config.num_solutions:
                break

            setup_index = None if config.icl is None else select_setup_index(config, attempts, rng)
            setup_name = None if setup_index is None else config.icl.setups[setup_index].name
            attempts += 1

            if config.is_agentic:
                loop = await run_agentic_loop(
                    client, config, prompt.messages(setup_index), ctx
                )
                meta = loop.meta()
                content = loop.content
            else:
                result = await call_api(
                    client,
                    config.api_url,
                    config.model,
                    prompt.messages(setup_index),
                    config.temperature,
                    config.max_tokens,
                    ctx,
                    api_type=config.api_type,
                    chat_template=config.chat_template,
                )
                meta = result.meta
                content = result.content if result.ok else None

            if content is None:
                meta["icl_setup"] = setup_name
                meta["evaluation_passed"] = False if has_eval else None
                if has_schema:
                    meta["schema_valid"] = False
                    meta["schema_error"] = "No response content to validate"
                metas.append(meta)
                continue

            value: Any = content
            if has_schema:
                schema = check_output_schema(config.output_schema, content)
                meta["schema_valid"] = schema.valid
                if not schema.valid:
                    meta["schema_error"] = schema.error
                    meta["icl_setup"] = setup_name
                    meta["evaluation_passed"] = False if has_eval else None
                    metas.append(meta)
                    continue
                value = schema.value

            outcome = await evaluate_response(client, config, content, row, index, ctx)
            if outcome.judge_meta is not None:
                meta["judge_meta"] = outcome.judge_meta
            meta["icl_setup"] = setup_name
            meta["evaluation_passed"] = outcome.passed
            metas.append(meta)

            if outcome.passed:
                passed_count += 1
            keep = outcome.passed if has_eval else True
            if keep:
                accepted += 1
            if not gated or keep:
                outputs.append({config.output_field: value, "icl_setup": setup_name})
    except BudgetStop:
        if not outputs:
            raise
        attempts = len(metas)

    passed = passed_count if has_eval else len(outputs)
    return {
        "input": row,
        "output": outputs,
        "result": {
            "passed": passed,
            "failed": attempts - passed,
            "attempts": attempts,
        },
        "meta": metas,
    }


def choose_concurrency(config: Config, row_count: int) -> int:
    """How many rows of a task may be in flight at once."""
    if row_count <= 0:
        return 1
    base = config.rpm if config.rpm else DEFAULT_CONCURRENCY_BASE
    limit = max(8, min(base, 256))
    if config.max_concurrent:
        # the limiter caps requests; rows must be able to saturate that cap
        limit = max(limit, config.max_concurrent)
    return max(1, min(limit, row_count))


@dataclass
class TaskRun:
    config: Config
    rows: list[dict]
    prompts: list[RowPrompt]
    output_path: str
    counter: Counter = field(default_factory=Counter)
    results: list[dict] = field(default_factory=list)
    resumed_from: int = 0
    kept_lines: list[str] = field(default_factory=list)  # resumed rows kept as-is


async def run_tasks(
    runs: list[TaskRun], progress: bool = False, tracker: "CostTracker | None" = None
) -> Counter:
    """Run every task concurrently over one shared connection pool."""
    global_counter = Counter()
    active = [run for run in runs if run.rows]
    for run in runs:
        run.counter = Counter(parent=global_counter)
        run.results = []
    tracker = tracker if tracker is not None else CostTracker()
    if not active:
        return global_counter

    reporter: Progress | None = None
    if progress:
        reporter = Progress(
            total=sum(len(run.rows) for run in active),
            counter=global_counter,
            tracker=tracker,
            show_eval=any(
                run.config.evaluation is not None or run.config.output_schema is not None
                for run in active
            ),
            show_cost=any(run.config.cost.configured for run in active),
        )

    sizes = {id(run): choose_concurrency(run.config, len(run.rows)) for run in active}
    pool = min(sum(sizes.values()), 1024)
    limits = httpx.Limits(max_connections=pool + 8, max_keepalive_connections=pool + 8)
    timeout = httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=600.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        coros = []
        for run in active:
            concurrency = sizes[id(run)]
            semaphore = asyncio.Semaphore(concurrency)
            slots: list[dict | None] = [None] * len(run.rows)
            run.results = slots  # type: ignore[assignment]
            ctx = RunContext(
                config=run.config,
                counter=run.counter,
                limiter=RateLimiter(run.config.rate_limits),
                tracker=tracker,
            )

            # Gentle ramp: avoids a thundering herd of simultaneous connects on
            # servers with a small listen backlog, without pacing below capacity.
            ramp = min(0.004, 0.25 / concurrency) if concurrency > 1 else 0.0

            def make_worker(run: TaskRun, semaphore, slots, concurrency, ramp, ctx):
                async def worker(index: int) -> None:
                    if index < concurrency and ramp:
                        await asyncio.sleep(index * ramp)
                    record: dict | None = None
                    async with semaphore:
                        if not ctx.budget_spent:
                            try:
                                record = await process_row(
                                    client,
                                    run.config,
                                    run.rows[index],
                                    run.prompts[index],
                                    ctx,
                                    index,
                                )
                            except BudgetStop:
                                # the budget ran out before this row could finish
                                record = None
                        else:
                            ctx.tracker.stopped = True
                    slots[index] = record
                    if reporter is not None:
                        reporter.row_done(record)

                return worker

            worker = make_worker(run, semaphore, slots, concurrency, ramp, ctx)
            coros.extend(worker(i) for i in range(len(run.rows)))

        await asyncio.gather(*coros)

    for run in runs:
        # a budget stop can leave rows unprocessed; keep the leading complete run
        # so the output stays a prefix of the input that `--resume` can extend
        kept: list[dict] = []
        for record in run.results:
            if record is None:
                break
            kept.append(record)
        run.results = kept

    if reporter is not None:
        reporter.emit(final=True)

    return global_counter


# --------------------------------------------------------------------------
# summary + output
# --------------------------------------------------------------------------


def record_passed(record: dict) -> bool:
    """Whether one output record counts as a passing row."""
    result = record.get("result") or {}
    row_passed = result.get("passed")
    output = record.get("output")
    if isinstance(output, list):
        # part 3 list format: the row passes when it yielded a passing solution
        return isinstance(row_passed, int) and row_passed >= 1
    has_output = output is not None
    return row_passed is True or (row_passed is None and has_output)


def _tally(results: list[dict]) -> tuple[int, int, int, int, int]:
    """(rows passed, rows failed, prompt tokens, completion tokens, solutions)."""
    passed = failed = prompt_tokens = completion_tokens = solutions = 0
    for record in results:
        metas = record["meta"]
        if isinstance(metas, dict):
            metas = [metas]
        elif metas is None:
            metas = []
        for meta in metas:
            # agentic metas aggregate their iterations under total_* keys
            prompt_tokens += meta.get("prompt_tokens") or meta.get("total_prompt_tokens") or 0
            completion_tokens += (
                meta.get("completion_tokens") or meta.get("total_completion_tokens") or 0
            )
            judge_meta = meta.get("judge_meta")
            if isinstance(judge_meta, dict):
                prompt_tokens += judge_meta.get("prompt_tokens") or 0
                completion_tokens += judge_meta.get("completion_tokens") or 0

        output = record["output"]
        if isinstance(output, list):
            solutions += len(output)
        else:
            solutions += 1 if output is not None else 0
        if record_passed(record):
            passed += 1
        else:
            failed += 1
    return passed, failed, prompt_tokens, completion_tokens, solutions


def _avg(solutions: int, rows: int) -> float:
    return round(solutions / rows, 2) if rows else 0.0


def build_summary(
    runs: list[TaskRun],
    counter: Counter,
    multi: bool,
    tracker: "CostTracker | None" = None,
    resumed: bool = False,
) -> dict:
    total = passed = failed = prompt_tokens = completion_tokens = solutions = 0
    resumed_from = 0
    per_task: dict[str, dict] = {}
    any_multi = any(run.config.list_format for run in runs)

    for run in runs:
        t_passed, t_failed, t_prompt, t_completion, t_solutions = _tally(run.results)
        total += len(run.results)
        passed += t_passed
        failed += t_failed
        prompt_tokens += t_prompt
        completion_tokens += t_completion
        solutions += t_solutions
        resumed_from += run.resumed_from
        entry = {
            "total": len(run.results),
            "passed": t_passed,
            "failed": t_failed,
            "total_solutions": t_solutions,
            "avg_solutions_per_input": _avg(t_solutions, len(run.results)),
            "total_api_calls": run.counter.api_calls,
        }
        if resumed:
            entry["resumed_from"] = run.resumed_from
        per_task[run.config.name] = entry

    if counter.first_request_at is not None and counter.last_response_at is not None:
        elapsed = max(0.0, counter.last_response_at - counter.first_request_at)
    else:
        elapsed = 0.0

    throughput = (counter.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0

    summary: dict[str, Any] = {"total": total}
    if resumed:
        summary["resumed_from"] = resumed_from
    summary.update(
        {
            "passed": passed,
            "failed": failed,
            "total_prompt_tokens": prompt_tokens,
            "total_completion_tokens": completion_tokens,
            "total_api_calls": counter.api_calls,
            "elapsed_seconds": round(elapsed, 1),
            "throughput_rpm": round(throughput, 1),
        }
    )
    cost_block = build_cost_summary(runs, tracker)
    if cost_block is not None:
        summary["cost"] = cost_block
    if any_multi:
        # only meaningful once a run can emit several solutions per input
        summary["total_solutions"] = solutions
        summary["avg_solutions_per_input"] = _avg(solutions, total)
    if multi:
        summary["tasks"] = per_task
    return summary


def build_cost_summary(runs: list[TaskRun], tracker: "CostTracker | None") -> dict | None:
    """The summary's `cost` block, or None when no task tracks cost."""
    if tracker is None or not any(run.config.cost.configured for run in runs):
        return None
    budgets = [
        run.config.cost.budget for run in runs if run.config.cost.budget is not None
    ]
    budget = min(budgets) if budgets else None
    total = round(tracker.total, COST_DIGITS)
    block: dict[str, Any] = {
        "total": total,
        "prompt": round(tracker.prompt, COST_DIGITS),
        "completion": round(tracker.completion, COST_DIGITS),
        "budget": budget,
        "budget_remaining": None if budget is None else round(budget - tracker.total, COST_DIGITS),
        "budget_exceeded": budget is not None and tracker.total >= budget,
    }
    return block


def write_results(path: str, results: list[dict], kept_lines: list[str] | None = None) -> None:
    """Write one JSON object per line; `kept_lines` are resumed rows to keep first."""
    try:
        with open(path, "w", encoding="utf-8") as handle:
            for line in kept_lines or []:
                handle.write(line.rstrip("\n") + "\n")
            for record in results:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ConfigError(f"could not write output file {path}: {exc}") from None


# --------------------------------------------------------------------------
# resume + dry run
# --------------------------------------------------------------------------


def record_complete(record: Any, config: Config) -> bool:
    """Whether an existing output row is finished, or must be redone from scratch."""
    if not isinstance(record, dict) or "result" not in record:
        return False
    output = record.get("output")
    if isinstance(output, list) or config.list_format:
        if not isinstance(output, list):
            return False
        target = max(1, min(config.num_solutions, _attempt_budget(config)))
        return len(output) >= target
    if config.scheme == "rejection":
        # a rejection row without a passing solution is not a finished row
        return output is not None
    return True


def apply_resume(run: TaskRun) -> None:
    """Skip the leading input rows that the output file already covers."""
    path = run.output_path
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = [line for line in handle.read().splitlines() if line.strip()]
    except OSError as exc:
        raise ConfigError(f"could not read output file {path}: {exc}") from None

    keep = 0
    for line in lines:
        if keep >= len(run.rows):
            break
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            break
        if not record_complete(record, run.config):
            break
        keep += 1

    run.resumed_from = keep
    run.kept_lines = lines[:keep]
    run.rows = run.rows[keep:]
    run.prompts = run.prompts[keep:]


def dry_run_attempts(config: Config) -> int:
    """Worst-case attempts per input used by the time estimate."""
    if config.scheme == "rejection":
        return config.max_attempts if config.list_format else config.n
    return 1


def dry_run_estimate(runs: list[TaskRun]) -> dict:
    """`--dry-run`: inputs, tokens, cost and time without touching the API."""
    tasks: dict[str, dict] = {}
    total_inputs = 0
    total_tokens = 0
    total_cost = 0.0
    total_minutes = 0.0

    for run in runs:
        config = run.config
        inputs = len(run.rows)
        words = [
            count_words(messages_text(prompt.base, config.api_type, config.chat_template))
            for prompt in run.prompts
        ]
        avg_words = (sum(words) / len(words)) if words else 0.0
        est_prompt = int(round(inputs * avg_words * DRY_RUN_TOKENS_PER_WORD))
        est_completion = inputs * config.max_tokens
        est_total = est_prompt + est_completion
        prompt_cost, completion_cost = config.cost.call_cost(est_prompt, est_completion)
        attempts = dry_run_attempts(config)
        minutes = (inputs * attempts / config.rpm) if config.rpm else 0.0

        tasks[config.name] = {
            "inputs": inputs,
            "est_prompt_tokens": est_prompt,
            "est_completion_tokens": est_completion,
            "est_total_tokens": est_total,
            "est_cost": round(prompt_cost + completion_cost, COST_DIGITS),
        }
        total_inputs += inputs
        total_tokens += est_total
        total_cost += prompt_cost + completion_cost
        total_minutes += minutes

    return {
        "tasks": tasks,
        "total_inputs": total_inputs,
        "est_total_tokens": total_tokens,
        "est_total_cost": round(total_cost, COST_DIGITS),
        "est_time_minutes": round(total_minutes, 2),
    }


# --------------------------------------------------------------------------
# planning (config + CLI -> task runs)
# --------------------------------------------------------------------------


@dataclass
class Plan:
    runs: list[TaskRun]
    multi: bool


def _selected_names(args: argparse.Namespace, available: list[str]) -> list[str]:
    if not args.task:
        return list(available)
    selected: list[str] = []
    for name in args.task:
        name = str(name).strip()
        if name not in available:
            raise ConfigError(
                f"--task {name!r} is not defined in the config "
                f"(available: {', '.join(available)})"
            )
        if name not in selected:
            selected.append(name)
    return selected


def _resolve_output_dir(path: str) -> str:
    if os.path.exists(path) and not os.path.isdir(path):
        raise ConfigError(f"--output must be a directory for multi-task configs: {path}")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"could not create output directory {path}: {exc}") from None
    return path


def _multi_inputs(args: argparse.Namespace, available: list[str], selected: list[str]) -> dict:
    if args.input and args.input_dir:
        raise ConfigError(
            "--input and --input-dir are alternative modes; pass one or the other"
        )

    mapping: dict[str, str] = {}
    if args.input:
        for item in args.input:
            if "=" not in item:
                raise ConfigError(
                    f"--input must be given as <task>=<path> for multi-task configs, got {item!r}"
                )
            name, path = item.split("=", 1)
            name = name.strip()
            if name not in available:
                raise ConfigError(
                    f"--input refers to unknown task {name!r} "
                    f"(available: {', '.join(available)})"
                )
            if path.strip() == "":
                raise ConfigError(f"--input for task {name!r} has an empty path")
            mapping[name] = path
    elif args.input_dir:
        if not os.path.isdir(args.input_dir):
            raise ConfigError(f"input directory not found: {args.input_dir}")
        for name in selected:
            mapping[name] = os.path.join(args.input_dir, f"{name}.jsonl")
    else:
        raise ConfigError("one of --input <task=path> or --input-dir is required")

    resolved: dict[str, str] = {}
    for name in selected:
        path = mapping.get(name)
        if path is None:
            raise ConfigError(f"no input file given for task {name!r} (use --input {name}=<path>)")
        if not os.path.exists(path):
            raise ConfigError(f"input file not found for task {name!r}: {path}")
        resolved[name] = path
    return resolved


def _single_input(args: argparse.Namespace, name: str) -> str:
    if args.input and args.input_dir:
        raise ConfigError(
            "--input and --input-dir are alternative modes; pass one or the other"
        )
    if args.input:
        if len(args.input) > 1:
            raise ConfigError("--input may only be given once for single-task configs")
        item = args.input[0]
        if "=" in item:
            prefix, rest = item.split("=", 1)
            if prefix.strip() == name:
                return rest
        return item
    if args.input_dir:
        if not os.path.isdir(args.input_dir):
            raise ConfigError(f"input directory not found: {args.input_dir}")
        path = os.path.join(args.input_dir, f"{name}.jsonl")
        if not os.path.exists(path):
            raise ConfigError(f"input file not found for task {name!r}: {path}")
        return path
    raise ConfigError("--input is required")


def build_plan(raw: dict, args: argparse.Namespace) -> Plan:
    config_dir = os.path.dirname(os.path.abspath(args.config)) or "."
    if is_multi_config(raw):
        defaults = _require_mapping(raw.get("defaults") or {}, "defaults")
        tasks = _require_mapping(raw.get("tasks"), "tasks")
        if not tasks:
            raise ConfigError("config: 'tasks' must contain at least one task")

        available = [str(key) for key in tasks]
        selected = _selected_names(args, available)
        if not selected:
            raise ConfigError("config: no tasks selected")

        # configs first, so a broken task is reported before any path juggling
        configs: dict[str, Config] = {}
        for name in selected:
            body = _require_mapping(tasks[name] or {}, f"tasks.{name}")
            configs[name] = build_config(
                deep_merge(defaults, body), args, name, f"tasks.{name}", config_dir
            )

        inputs = _multi_inputs(args, available, selected)
        output_dir = _resolve_output_dir(args.output)

        runs: list[TaskRun] = []
        for name in selected:
            config = configs[name]
            rows = load_rows(inputs[name])
            try:
                prompts = prepare_prompts(config, rows)
            except ConfigError as exc:
                raise ConfigError(f"task {name!r}: {exc}") from None
            runs.append(
                TaskRun(
                    config=config,
                    rows=rows,
                    prompts=prompts,
                    output_path=os.path.join(output_dir, f"{name}.jsonl"),
                )
            )
        return Plan(runs=runs, multi=True)

    if "task" not in raw:
        raise ConfigError("config: missing required section 'task'")
    task = _require_mapping(raw["task"], "task")
    name = str(task.get("name", "task"))
    _selected_names(args, [name])
    config = build_config(task, args, name, "task", config_dir)
    rows = load_rows(_single_input(args, name))
    prompts = prepare_prompts(config, rows)
    return Plan(
        runs=[TaskRun(config=config, rows=rows, prompts=prompts, output_path=args.output)],
        multi=False,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # noqa: D102 - argparse hook
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="rejector.py", description="Run generation tasks against an OpenAI-compatible API."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one or more tasks over JSONL input")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument(
        "--input",
        action="append",
        default=None,
        help="JSONL input file, or <task>=<path> for multi-task configs (repeatable)",
    )
    run.add_argument(
        "--input-dir",
        dest="input_dir",
        default=None,
        help="directory holding <task_name>.jsonl for each task",
    )
    run.add_argument("--output", required=True, help="JSONL output file, or directory for multi-task")
    run.add_argument("--task", action="append", default=None, help="run only this task (repeatable)")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--eval-model", dest="eval_model", default=None, help="override llm_judge model")
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--tpm", type=int, default=None, help="token-per-minute budget")
    run.add_argument(
        "--max-concurrent",
        dest="max_concurrent",
        type=int,
        default=None,
        help="hard cap on in-flight API requests per task",
    )
    run.add_argument(
        "--budget", type=float, default=None, help="stop scheduling once this spend is reached"
    )
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", choices=list(SCHEMES), default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    run.add_argument(
        "--num-solutions",
        dest="num_solutions",
        type=int,
        default=None,
        help="number of solutions to collect per input",
    )
    run.add_argument(
        "--icl-strategy",
        dest="icl_strategy",
        choices=list(ICL_STRATEGIES),
        default=None,
        help="how ICL setups are chosen across attempts",
    )
    run.add_argument(
        "--api-type",
        dest="api_type",
        choices=list(API_TYPES),
        default=None,
        help="chat (/v1/chat/completions) or completions (/v1/completions)",
    )
    run.add_argument(
        "--chat-template",
        dest="chat_template",
        choices=list(CHAT_TEMPLATES),
        default=None,
        help="prompt template used to flatten messages in completions mode",
    )
    run.add_argument(
        "--resume",
        action="store_true",
        help="skip input rows already present in the output file and append",
    )
    run.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="validate config and inputs, print an estimate, make no API calls",
    )
    run.add_argument(
        "--progress",
        action="store_true",
        help="print progress updates to stderr while running",
    )
    run.add_argument(
        "--icl-k",
        dest="icl_k",
        type=int,
        default=None,
        help="number of ICL examples to use from the selected setup",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        raw = load_config(args.config)
        plan = build_plan(raw, args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if getattr(args, "dry_run", False):
        print(json.dumps(dry_run_estimate(plan.runs)))
        return EXIT_OK

    resume = bool(getattr(args, "resume", False))
    try:
        if resume:
            for run in plan.runs:
                apply_resume(run)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    tracker = CostTracker()
    try:
        counter = asyncio.run(
            run_tasks(plan.runs, progress=bool(getattr(args, "progress", False)), tracker=tracker)
        )
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return EXIT_ERROR

    try:
        for run in plan.runs:
            write_results(run.output_path, run.results, run.kept_lines if resume else None)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(json.dumps(build_summary(plan.runs, counter, plan.multi, tracker, resume)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
