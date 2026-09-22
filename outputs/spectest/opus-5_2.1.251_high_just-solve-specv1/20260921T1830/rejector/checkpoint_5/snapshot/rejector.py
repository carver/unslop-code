#!/usr/bin/env python3
"""rejector.py - batch prompting CLI for OpenAI-compatible chat completion APIs.

Reads a YAML config (one task, or many named tasks sharing `defaults`) plus a
JSONL input file per task, renders prompts for every row, issues chat-completion
requests concurrently (dispatched in input order), optionally evaluates each
response, and writes one JSONL result per input row.

Supported generation schemes: greedy, sample, rejection, agentic.
Supported evaluations: exact_match, contains, regex, script, llm_judge.
Optional in-context learning (ICL) setups supply few-shot examples, and a task
may collect several solutions per input (`num_solutions`). Requests go to
`/v1/chat/completions` or, with `api_type: completions`, to `/v1/completions`
with the conversation rendered through a built-in chat template. `agentic`
tasks let the model call configured tools in a loop before answering.
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
from dataclasses import dataclass, field
from typing import Any

import httpx
import yaml

EXIT_OK = 0
EXIT_ERROR = 1

SCHEMES = ("greedy", "sample", "rejection", "agentic")
ICL_STRATEGIES = ("fixed", "random", "round_robin")
EVAL_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")
API_TYPES = ("chat", "completions")
CHAT_TEMPLATES = ("chatml", "llama3", "mistral", "zephyr")
TOOL_HANDLER_TYPES = ("echo", "static_map", "script")

MAX_HTTP_ATTEMPTS = 3  # total requests per logical attempt: 1 try + 2 retries
RETRY_BACKOFF_SECONDS = (0.25, 0.5)
DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_OUTPUT_FIELD = "output"
MAX_CONCURRENCY = 512
MIN_CONCURRENCY = 8
RAMP_BUDGET_SECONDS = 0.25
MAX_STAGGER_SECONDS = 0.005

SCRIPT_TIMEOUT_SECONDS = 10.0
KILL_GRACE_SECONDS = 5.0
DEFAULT_SUCCESS_EXIT_CODE = 0
JUDGE_TEMPERATURE = 0.0  # judging should be deterministic
RESPONSE_PLACEHOLDER = "__response__"

DEFAULT_ICL_STRATEGY = "fixed"
DEFAULT_NUM_SOLUTIONS = 1
# `max_attempts` default for rejection sampling when several solutions are wanted.
REJECTION_ATTEMPT_MULTIPLIER = 3

DEFAULT_API_TYPE = "chat"
DEFAULT_CHAT_TEMPLATE = "chatml"
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_STATIC_MAP_MISS = "NOT_FOUND"
TOOL_TIMEOUT_SECONDS = 10.0
MAX_ITERATIONS_REASON = "max_iterations"

# Token-aware scheduling.
RATE_WINDOW_SECONDS = 60.0
WORDS_PER_TOKEN = 0.75  # `1 token ~= 0.75 words` when estimating a prompt
MIN_LIMITER_SLEEP = 0.005
# Dry-run planning uses a coarser words -> tokens factor.
DRY_RUN_TOKEN_FACTOR = 1.33
COST_DECIMALS = 6  # "at least four decimal places"

PROGRESS_INTERVAL_SECONDS = 5.0
PROGRESS_FRACTION = 0.1
PROGRESS_POLL_SECONDS = 0.2

JSON_SCHEMA_TYPES = (
    "object",
    "array",
    "string",
    "number",
    "integer",
    "boolean",
    "null",
)


class ConfigError(Exception):
    """Configuration or input problem; reported on stderr with exit code 1."""


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass
class EvaluationConfig:
    type: str
    answer_field: str | None = None
    pattern: str | None = None
    extract: str | None = None  # as configured (may be None)
    compiled: re.Pattern[str] | None = None
    # script
    command_template: str | None = None
    success_exit_code: int = DEFAULT_SUCCESS_EXIT_CODE
    # llm_judge
    judge_system: str | None = None
    judge_user: str | None = None
    threshold: float | None = None
    model: str | None = None

    @property
    def extract_method(self) -> str:
        if self.extract:
            return self.extract
        return "first_number" if self.type == "llm_judge" else "full"


@dataclass
class IclExample:
    """One few-shot example: a row-shaped input and the assistant reply."""

    input: dict
    output: str


@dataclass
class IclSetup:
    name: str
    examples: list[IclExample]
    messages: list[dict] = field(default_factory=list)  # rendered user/assistant turns


@dataclass
class ToolHandler:
    """How a tool call is answered: echoed, looked up, or run as a command."""

    type: str
    mapping: dict[str, str] = field(default_factory=dict)
    default: str = DEFAULT_STATIC_MAP_MISS
    command: str | None = None
    arg_field: str | None = None


@dataclass
class ToolConfig:
    name: str
    description: str
    parameters: dict
    handler: ToolHandler

    def definition(self) -> dict:
        """The tool as the model sees it (OpenAI function shape, unwrapped)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class IclConfig:
    setups: list[IclSetup]
    k: int | None = None
    strategy: str = DEFAULT_ICL_STRATEGY


@dataclass
class CostConfig:
    """Per-1k token prices and an optional budget for a task."""

    prompt_cost_per_1k: float = 0.0
    completion_cost_per_1k: float = 0.0
    budget: float | None = None

    def call_cost(self, prompt_tokens: int, completion_tokens: int) -> tuple[float, float]:
        return (
            prompt_tokens / 1000.0 * self.prompt_cost_per_1k,
            completion_tokens / 1000.0 * self.completion_cost_per_1k,
        )


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
    output_field: str
    evaluation: EvaluationConfig | None = None
    icl: IclConfig | None = None
    num_solutions: int = DEFAULT_NUM_SOLUTIONS
    configured_max_attempts: int | None = None
    api_type: str = DEFAULT_API_TYPE
    chat_template: str = DEFAULT_CHAT_TEMPLATE
    tools: list[ToolConfig] = field(default_factory=list)
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    tpm: int | None = None
    max_concurrent: int | None = None
    cost: CostConfig | None = None
    output_schema: dict | None = None

    @property
    def effective_rpm(self) -> int:
        """The rpm used for pool sizing and planning when limiting is disabled."""
        return self.rpm if self.rpm else DEFAULT_RPM

    @property
    def gates_output(self) -> bool:
        """True when the task decides pass/fail (evaluation and/or a schema)."""
        return self.evaluation is not None or self.output_schema is not None

    @property
    def endpoint(self) -> str:
        base = self.api_url.rstrip("/")
        if self.api_type == "completions":
            return base + "/v1/completions"
        return base + "/v1/chat/completions"

    def tool_definitions(self) -> list[dict] | None:
        """Native `tools` request field; None when there is nothing to send."""
        if not self.tools:
            return None
        return [{"type": "function", "function": tool.definition()} for tool in self.tools]

    def tool_by_name(self, name: str) -> ToolConfig | None:
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def api_request(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float | None = None,
        tools: list[dict] | None = None,
    ) -> "ApiRequest":
        return ApiRequest(
            endpoint=self.endpoint,
            model=model or self.model,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens,
            messages=messages,
            api_type=self.api_type,
            chat_template=self.chat_template,
            tools=tools,
        )

    @property
    def legacy(self) -> bool:
        """True when the Part 1 single-solution behaviour and output shape apply."""
        return self.icl is None and self.num_solutions == 1

    @property
    def max_attempts(self) -> int:
        """Logical attempts per row on the legacy (Part 1) path."""
        return self.n if self.scheme == "rejection" else 1

    @property
    def attempt_budget(self) -> int:
        """Upper bound on generation attempts per row on the multi-solution path."""
        if self.scheme == "agentic":
            # Each requested solution is one independent agentic loop.
            return max(1, self.num_solutions)
        if self.scheme == "greedy":
            setups = len(self.icl.setups) if self.icl is not None else 1
            return max(1, min(self.num_solutions, setups))
        if self.scheme == "sample":
            return self.num_solutions
        if self.configured_max_attempts is not None:
            return self.configured_max_attempts
        return REJECTION_ATTEMPT_MULTIPLIER * self.num_solutions

    @property
    def judge_model(self) -> str:
        if self.evaluation is not None and self.evaluation.model:
            return self.evaluation.model
        return self.model


@dataclass
class ConfigBundle:
    tasks: list[TaskConfig]  # selected tasks, in config order
    multi: bool
    all_names: list[str]


def _require_mapping(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _as_str(value: Any, label: str) -> str:
    if value is None:
        raise ConfigError(f"{label} is required")
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ConfigError(f"{label} must be a string")
    text = str(value).strip()
    if not text:
        raise ConfigError(f"{label} must be a non-empty string")
    return text


def _as_int(value: Any, label: str, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{label} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ConfigError(f"{label} must be an integer, got {value!r}")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{label} must be an integer, got {value!r}") from None
    if number < minimum:
        raise ConfigError(f"{label} must be >= {minimum}, got {number}")
    return number


def _as_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ConfigError(f"{label} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{label} must be a number, got {value!r}") from None


def deep_merge(base: Any, override: Any) -> Any:
    """Merge `override` over `base`; nested mappings merge key by key."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    return override


def load_config(
    path: str, overrides: dict[str, Any], selected: list[str] | None = None
) -> ConfigBundle:
    """Load, merge, override and validate the YAML configuration.

    Single-task configs (a top-level `task` key) keep the Part 1 shape.
    Multi-task configs use `defaults` plus a `tasks` mapping.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in config file {path}: {exc}") from None

    if raw is None:
        raise ConfigError(f"config file {path} is empty")
    root = _require_mapping(raw, "config")

    # ICL example files are resolved relative to the config file's directory.
    config_dir = os.path.dirname(os.path.abspath(path)) or "."

    defaults = root.get("defaults")
    defaults = {} if defaults is None else _require_mapping(defaults, "defaults")

    if root.get("task") is not None:
        body = _require_mapping(root["task"], "task")
        merged = deep_merge(defaults, body)
        raw_name = merged.get("name")
        name = str(raw_name).strip() if raw_name is not None else ""
        name = name or "task"
        chosen = _select_names([name], selected)
        task = _build_task(name, merged, overrides, "task", config_dir)
        return ConfigBundle(tasks=[task] if chosen else [], multi=False, all_names=[name])

    if root.get("tasks") is None:
        raise ConfigError("config must contain a top-level 'task' or 'tasks' section")

    tasks_raw = _require_mapping(root["tasks"], "tasks")
    if not tasks_raw:
        raise ConfigError("config 'tasks' section must define at least one task")

    all_names: list[str] = []
    bodies: dict[str, Any] = {}
    for key, value in tasks_raw.items():
        name = _as_str(key, "task name in 'tasks'")
        if name in bodies:
            raise ConfigError(f"duplicate task name {name!r} in 'tasks'")
        if name in (".", "..") or "/" in name or "\\" in name or os.sep in name:
            raise ConfigError(f"task name {name!r} must not contain path separators")
        all_names.append(name)
        bodies[name] = value

    chosen = _select_names(all_names, selected)
    tasks = []
    for name in chosen:
        body = bodies[name]
        if body is None:
            body = {}
        body = _require_mapping(body, f"tasks.{name}")
        merged = deep_merge(defaults, body)
        tasks.append(_build_task(name, merged, overrides, f"tasks.{name}", config_dir))
    return ConfigBundle(tasks=tasks, multi=True, all_names=all_names)


def _select_names(all_names: list[str], selected: list[str] | None) -> list[str]:
    if not selected:
        return list(all_names)
    wanted: list[str] = []
    for name in selected:
        if name not in all_names:
            available = ", ".join(all_names)
            raise ConfigError(
                f"--task {name!r} is not defined in the config (available: {available})"
            )
        if name not in wanted:
            wanted.append(name)
    return [name for name in all_names if name in wanted]


def _build_task(
    name: str,
    task: dict,
    overrides: dict[str, Any],
    label: str,
    config_dir: str = ".",
) -> TaskConfig:
    api_url = overrides.get("api_url") or task.get("api_url")
    api_url = _as_str(api_url, f"{label}.api_url")
    if not re.match(r"^https?://", api_url):
        raise ConfigError(
            f"{label}.api_url must start with http:// or https://, got {api_url!r}"
        )

    model = overrides.get("model") or task.get("model")
    model = _as_str(model, f"{label}.model")

    rate_limits = task.get("rate_limits")
    rate_limits = (
        {} if rate_limits is None else _require_mapping(rate_limits, f"{label}.rate_limits")
    )

    # `rate_limits.rpm` is the new home of the old top-level `rpm`; either works.
    rpm_value = overrides.get("rpm")
    if rpm_value is None:
        rpm_value = rate_limits.get("rpm")
    if rpm_value is None:
        rpm_value = task.get("rpm")
    # An omitted rpm disables request-rate limiting for the task.
    rpm = None if rpm_value is None else _as_int(rpm_value, f"{label}.rate_limits.rpm", minimum=1)

    tpm_value = overrides.get("tpm")
    if tpm_value is None:
        tpm_value = rate_limits.get("tpm")
    if tpm_value is None:
        tpm_value = task.get("tpm")
    tpm = None if tpm_value is None else _as_int(tpm_value, f"{label}.rate_limits.tpm", minimum=1)

    concurrent_value = overrides.get("max_concurrent")
    if concurrent_value is None:
        concurrent_value = rate_limits.get("max_concurrent")
    if concurrent_value is None:
        concurrent_value = task.get("max_concurrent")
    max_concurrent = (
        None
        if concurrent_value is None
        else _as_int(concurrent_value, f"{label}.rate_limits.max_concurrent", minimum=1)
    )

    cost = parse_cost(task.get("cost"), f"{label}.cost", overrides)
    output_schema = parse_output_schema(task.get("output_schema"), f"{label}.output_schema")

    prompt = task.get("prompt")
    if prompt is None:
        raise ConfigError(f"{label}.prompt is required")
    prompt = _require_mapping(prompt, f"{label}.prompt")
    if prompt.get("user") is None:
        raise ConfigError(f"{label}.prompt.user is required")
    user_template = prompt["user"]
    if not isinstance(user_template, str):
        raise ConfigError(f"{label}.prompt.user must be a string")
    system_template = prompt.get("system")
    if system_template is not None and not isinstance(system_template, str):
        raise ConfigError(f"{label}.prompt.system must be a string")

    generation = task.get("generation") or {}
    generation = _require_mapping(generation, f"{label}.generation")

    api_type_value = (
        overrides.get("api_type")
        or task.get("api_type")
        or generation.get("api_type")
        or DEFAULT_API_TYPE
    )
    api_type = str(api_type_value).strip().lower()
    if api_type not in API_TYPES:
        raise ConfigError(
            f"{label}.api_type must be one of {', '.join(API_TYPES)}, got {api_type!r}"
        )

    template_value = (
        overrides.get("chat_template")
        or task.get("chat_template")
        or generation.get("chat_template")
        or DEFAULT_CHAT_TEMPLATE
    )
    chat_template = str(template_value).strip().lower()
    if chat_template not in CHAT_TEMPLATES:
        raise ConfigError(
            f"{label}.chat_template must be one of {', '.join(CHAT_TEMPLATES)}, "
            f"got {chat_template!r}"
        )

    scheme = overrides.get("scheme") or generation.get("scheme") or "greedy"
    scheme = str(scheme).strip().lower()
    if scheme not in SCHEMES:
        raise ConfigError(
            f"{label}.generation.scheme must be one of {', '.join(SCHEMES)}, "
            f"got {scheme!r}"
        )

    temperature_value = overrides.get("temperature")
    if temperature_value is None:
        temperature_value = generation.get("temperature", 0.0)
    temperature = _as_float(temperature_value, f"{label}.generation.temperature")
    if temperature < 0:
        raise ConfigError(
            f"{label}.generation.temperature must be >= 0, got {temperature}"
        )

    max_tokens_value = overrides.get("max_tokens")
    if max_tokens_value is None:
        max_tokens_value = generation.get("max_tokens", DEFAULT_MAX_TOKENS)
    max_tokens = _as_int(max_tokens_value, f"{label}.generation.max_tokens", minimum=1)

    n_value = overrides.get("n")
    if n_value is None:
        n_value = generation.get("n", 1)
    n = _as_int(n_value, f"{label}.generation.n", minimum=1)

    iterations_value = generation.get("max_iterations")
    if iterations_value is None:
        iterations_value = task.get("max_iterations")
    max_iterations = (
        DEFAULT_MAX_ITERATIONS
        if iterations_value is None
        else _as_int(iterations_value, f"{label}.generation.max_iterations", minimum=1)
    )

    tools_raw = task.get("tools")
    if tools_raw is None:
        tools_raw = generation.get("tools")
    tools = parse_tools(tools_raw, f"{label}.tools")

    max_attempts_value = generation.get("max_attempts")
    configured_max_attempts = (
        None
        if max_attempts_value is None
        else _as_int(max_attempts_value, f"{label}.generation.max_attempts", minimum=1)
    )

    num_solutions_value = overrides.get("num_solutions")
    if num_solutions_value is None:
        num_solutions_value = task.get("num_solutions")
    if num_solutions_value is None:
        num_solutions_value = generation.get("num_solutions", DEFAULT_NUM_SOLUTIONS)
    num_solutions = _as_int(num_solutions_value, f"{label}.num_solutions", minimum=1)

    output_field = task.get("output_field", DEFAULT_OUTPUT_FIELD)
    output_field = _as_str(output_field, f"{label}.output_field")

    icl = parse_icl(
        task.get("icl"), f"{label}.icl", overrides, config_dir, user_template
    )

    evaluation = parse_evaluation(
        task.get("evaluation"), f"{label}.evaluation", overrides
    )

    # Scheme-specific rules.
    if scheme == "greedy":
        temperature = 0.0
        n = 1
    elif scheme == "sample":
        if temperature <= 0:
            raise ConfigError(
                f"scheme 'sample' requires {label}.generation.temperature > 0, "
                f"got {temperature}"
            )
        n = 1
    elif scheme == "agentic":
        # Tool-calling loops run at whatever temperature is configured; `n` is unused.
        n = 1
    else:  # rejection
        if temperature <= 0:
            raise ConfigError(
                f"scheme 'rejection' requires {label}.generation.temperature > 0, "
                f"got {temperature}"
            )
        if evaluation is None and output_schema is None:
            raise ConfigError(
                f"scheme 'rejection' requires a {label}.evaluation section "
                f"or an {label}.output_schema"
            )

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
        output_field=output_field,
        evaluation=evaluation,
        icl=icl,
        num_solutions=num_solutions,
        configured_max_attempts=configured_max_attempts,
        api_type=api_type,
        chat_template=chat_template,
        tools=tools,
        max_iterations=max_iterations,
        tpm=tpm,
        max_concurrent=max_concurrent,
        cost=cost,
        output_schema=output_schema,
    )


def parse_evaluation(
    raw: Any, label: str = "task.evaluation", overrides: dict[str, Any] | None = None
) -> EvaluationConfig | None:
    if raw is None:
        return None
    overrides = overrides or {}
    section = _require_mapping(raw, label)
    eval_type = section.get("type")
    if eval_type is None:
        raise ConfigError(f"{label}.type is required")
    eval_type = str(eval_type).strip().lower()
    if eval_type not in EVAL_TYPES:
        raise ConfigError(
            f"{label}.type must be one of {', '.join(EVAL_TYPES)}, got {eval_type!r}"
        )

    extract = section.get("extract")
    if extract is not None:
        extract = str(extract).strip().lower()
        if extract not in EXTRACT_METHODS:
            raise ConfigError(
                f"{label}.extract must be one of {', '.join(EXTRACT_METHODS)}, "
                f"got {extract!r}"
            )

    answer_field = section.get("answer_field")
    pattern = section.get("pattern")
    compiled = None
    command_template = None
    success_exit_code = DEFAULT_SUCCESS_EXIT_CODE
    judge_system = None
    judge_user = None
    threshold = None
    judge_model = None

    if eval_type in ("exact_match", "contains"):
        if answer_field is None or str(answer_field).strip() == "":
            raise ConfigError(f"{label}.answer_field is required for type '{eval_type}'")
        answer_field = str(answer_field)
    elif eval_type == "regex":
        if pattern is None or str(pattern) == "":
            raise ConfigError(f"{label}.pattern is required for type 'regex'")
        pattern = str(pattern)
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"{label}.pattern is not a valid regex: {exc}") from None
        answer_field = str(answer_field) if answer_field is not None else None
    elif eval_type == "script":
        command_template = section.get("command_template")
        if command_template is None or str(command_template).strip() == "":
            raise ConfigError(f"{label}.command_template is required for type 'script'")
        if not isinstance(command_template, str):
            raise ConfigError(f"{label}.command_template must be a string")
        exit_value = section.get("success_exit_code", DEFAULT_SUCCESS_EXIT_CODE)
        success_exit_code = _as_int(exit_value, f"{label}.success_exit_code", minimum=0)
        answer_field = str(answer_field) if answer_field is not None else None
    else:  # llm_judge
        judge_prompt = section.get("judge_prompt")
        if judge_prompt is None:
            raise ConfigError(f"{label}.judge_prompt is required for type 'llm_judge'")
        judge_prompt = _require_mapping(judge_prompt, f"{label}.judge_prompt")
        if judge_prompt.get("user") is None:
            raise ConfigError(f"{label}.judge_prompt.user is required")
        judge_user = judge_prompt["user"]
        if not isinstance(judge_user, str):
            raise ConfigError(f"{label}.judge_prompt.user must be a string")
        judge_system = judge_prompt.get("system")
        if judge_system is not None and not isinstance(judge_system, str):
            raise ConfigError(f"{label}.judge_prompt.system must be a string")
        if section.get("threshold") is None:
            raise ConfigError(f"{label}.threshold is required for type 'llm_judge'")
        threshold = _as_float(section.get("threshold"), f"{label}.threshold")
        model_value = overrides.get("eval_model") or section.get("model")
        judge_model = (
            _as_str(model_value, f"{label}.model") if model_value is not None else None
        )
        answer_field = str(answer_field) if answer_field is not None else None

    return EvaluationConfig(
        type=eval_type,
        answer_field=answer_field,
        pattern=pattern,
        extract=extract,
        compiled=compiled,
        command_template=command_template,
        success_exit_code=success_exit_code,
        judge_system=judge_system,
        judge_user=judge_user,
        threshold=threshold,
        model=judge_model,
    )


def parse_cost(
    raw: Any, label: str = "task.cost", overrides: dict[str, Any] | None = None
) -> CostConfig | None:
    """Parse a `cost` section; `--budget` alone also turns cost tracking on."""
    overrides = overrides or {}
    budget_override = overrides.get("budget")
    if raw is None and budget_override is None:
        return None

    section = {} if raw is None else _require_mapping(raw, label)
    prompt_rate = section.get("prompt_cost_per_1k", 0.0)
    completion_rate = section.get("completion_cost_per_1k", 0.0)
    prompt_rate = _as_float(prompt_rate, f"{label}.prompt_cost_per_1k")
    completion_rate = _as_float(completion_rate, f"{label}.completion_cost_per_1k")
    if prompt_rate < 0 or completion_rate < 0:
        raise ConfigError(f"{label} rates must be >= 0")

    budget_value = budget_override
    if budget_value is None:
        budget_value = section.get("budget")
    budget = None if budget_value is None else _as_float(budget_value, f"{label}.budget")
    if budget is not None and budget < 0:
        raise ConfigError(f"{label}.budget must be >= 0, got {budget}")

    return CostConfig(
        prompt_cost_per_1k=prompt_rate,
        completion_cost_per_1k=completion_rate,
        budget=budget,
    )


def parse_output_schema(raw: Any, label: str = "task.output_schema") -> dict | None:
    """Validate the shape of a JSON Schema (draft 7 subset) before running."""
    if raw is None:
        return None
    schema = _require_mapping(raw, label)
    _check_schema_shape(schema, label)
    return schema


def _check_schema_shape(schema: dict, label: str) -> None:
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        for name in names:
            if not isinstance(name, str) or name not in JSON_SCHEMA_TYPES:
                raise ConfigError(
                    f"{label}.type must be one of {', '.join(JSON_SCHEMA_TYPES)}, "
                    f"got {name!r}"
                )

    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or any(
            not isinstance(name, str) for name in required
        ):
            raise ConfigError(f"{label}.required must be a list of field names")

    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        raise ConfigError(f"{label}.enum must be a non-empty list")

    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            raise ConfigError(f"{label}.pattern must be a string")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"{label}.pattern is not a valid regex: {exc}") from None

    for key in ("minimum", "maximum"):
        if schema.get(key) is not None:
            _as_float(schema[key], f"{label}.{key}")
    for key in ("minLength", "maxLength"):
        if schema.get(key) is not None:
            _as_int(schema[key], f"{label}.{key}", minimum=0)

    properties = schema.get("properties")
    if properties is not None:
        properties = _require_mapping(properties, f"{label}.properties")
        for key, value in properties.items():
            _check_schema_shape(
                _require_mapping(value, f"{label}.properties.{key}"),
                f"{label}.properties.{key}",
            )

    items = schema.get("items")
    if items is not None:
        if isinstance(items, list):
            for index, value in enumerate(items):
                _check_schema_shape(
                    _require_mapping(value, f"{label}.items[{index}]"),
                    f"{label}.items[{index}]",
                )
        else:
            _check_schema_shape(
                _require_mapping(items, f"{label}.items"), f"{label}.items"
            )


def parse_tools(raw: Any, label: str) -> list[ToolConfig]:
    """Parse a task's `tools` list (agentic generation)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"{label} must be a list of tool definitions")

    tools: list[ToolConfig] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        tool_label = f"{label}[{index}]"
        body = _require_mapping(entry, tool_label)
        name = _as_str(body.get("name"), f"{tool_label}.name")
        if name in seen:
            raise ConfigError(f"{label}: duplicate tool name {name!r}")
        seen.add(name)

        description = body.get("description")
        if description is not None and not isinstance(description, str):
            raise ConfigError(f"{tool_label}.description must be a string")

        parameters = body.get("parameters")
        if parameters is None:
            parameters = {"type": "object", "properties": {}}
        else:
            parameters = _require_mapping(parameters, f"{tool_label}.parameters")

        tools.append(
            ToolConfig(
                name=name,
                description=description or "",
                parameters=parameters,
                handler=parse_tool_handler(body.get("handler"), f"{tool_label}.handler"),
            )
        )
    return tools


def parse_tool_handler(raw: Any, label: str) -> ToolHandler:
    if raw is None:
        raise ConfigError(f"{label} is required")
    body = _require_mapping(raw, label)
    handler_type = body.get("type")
    if handler_type is None:
        raise ConfigError(f"{label}.type is required")
    handler_type = str(handler_type).strip().lower()
    if handler_type not in TOOL_HANDLER_TYPES:
        raise ConfigError(
            f"{label}.type must be one of {', '.join(TOOL_HANDLER_TYPES)}, "
            f"got {handler_type!r}"
        )

    mapping: dict[str, str] = {}
    default = DEFAULT_STATIC_MAP_MISS
    command = None
    arg_field = None

    if handler_type == "static_map":
        raw_mapping = body.get("mapping")
        if raw_mapping is not None:
            raw_mapping = _require_mapping(raw_mapping, f"{label}.mapping")
            mapping = {str(key): _stringify(value) for key, value in raw_mapping.items()}
        if body.get("default") is not None:
            default = _stringify(body.get("default"))
    elif handler_type == "script":
        command = _as_str(body.get("command"), f"{label}.command")
        arg_field = _as_str(body.get("arg_field"), f"{label}.arg_field")

    return ToolHandler(
        type=handler_type,
        mapping=mapping,
        default=default,
        command=command,
        arg_field=arg_field,
    )


def parse_icl(
    raw: Any,
    label: str,
    overrides: dict[str, Any],
    config_dir: str,
    user_template: str,
) -> IclConfig | None:
    """Parse an `icl` section, loading and rendering every setup's examples."""
    if raw is None:
        return None
    section = _require_mapping(raw, label)

    setups_raw = section.get("setups")
    if setups_raw is None:
        raise ConfigError(f"{label}.setups is required")
    if not isinstance(setups_raw, list) or not setups_raw:
        raise ConfigError(f"{label}.setups must be a non-empty list of setups")

    strategy_value = overrides.get("icl_strategy")
    if strategy_value is None:
        strategy_value = section.get("strategy", DEFAULT_ICL_STRATEGY)
    strategy = str(strategy_value).strip().lower()
    if strategy not in ICL_STRATEGIES:
        raise ConfigError(
            f"{label}.strategy must be one of {', '.join(ICL_STRATEGIES)}, "
            f"got {strategy!r}"
        )

    k_value = overrides.get("icl_k")
    if k_value is None:
        k_value = section.get("k")
    k = None if k_value is None else _as_int(k_value, f"{label}.k", minimum=1)

    setups: list[IclSetup] = []
    seen: set[str] = set()
    for index, entry in enumerate(setups_raw):
        setup_label = f"{label}.setups[{index}]"
        body = _require_mapping(entry, setup_label)
        name = _as_str(body.get("name"), f"{setup_label}.name")
        if name in seen:
            raise ConfigError(f"{label}: duplicate setup name {name!r}")
        seen.add(name)

        has_examples = body.get("examples") is not None
        has_file = body.get("file") is not None
        if has_examples == has_file:
            raise ConfigError(
                f"{setup_label} ({name!r}) must define exactly one of "
                f"'examples' or 'file'"
            )

        described = f"{label} setup {name!r}"
        if has_file:
            file_value = _as_str(body.get("file"), f"{setup_label}.file")
            examples = load_icl_file(file_value, config_dir, described)
        else:
            examples = parse_icl_examples(body.get("examples"), f"{setup_label}.examples")
        if not examples:
            raise ConfigError(f"{described} has no examples")

        # `k` defaults to every example; a smaller `k` keeps the first `k`.
        if k is not None:
            examples = examples[:k]
        setups.append(
            IclSetup(
                name=name,
                examples=examples,
                messages=render_icl_messages(examples, user_template, described),
            )
        )

    return IclConfig(setups=setups, k=k, strategy=strategy)


def _icl_example(value: Any, label: str) -> IclExample:
    body = _require_mapping(value, label)
    if "input" not in body:
        raise ConfigError(f"{label} is missing the required key 'input'")
    if "output" not in body:
        raise ConfigError(f"{label} is missing the required key 'output'")
    example_input = _require_mapping(body["input"], f"{label}.input")
    example_output = body["output"]
    if not isinstance(example_output, str):
        raise ConfigError(f"{label}.output must be a string")
    return IclExample(input=example_input, output=example_output)


def parse_icl_examples(raw: Any, label: str) -> list[IclExample]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{label} must be a non-empty list of examples")
    return [
        _icl_example(entry, f"{label}[{index}]") for index, entry in enumerate(raw)
    ]


def load_icl_file(relative: str, config_dir: str, label: str) -> list[IclExample]:
    """Read a JSONL file of ICL examples, relative to the config file directory."""
    path = relative if os.path.isabs(relative) else os.path.join(config_dir, relative)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise ConfigError(f"{label}: ICL example file not found: {path}") from None
    except IsADirectoryError:
        raise ConfigError(f"{label}: ICL example file is a directory: {path}") from None
    except OSError as exc:
        raise ConfigError(
            f"{label}: could not read ICL example file {path}: {exc}"
        ) from None

    examples: list[IclExample] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"{label}: line {lineno} of {path} is not valid JSON: {exc.msg}"
            ) from None
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("input"), dict)
            or not isinstance(value.get("output"), str)
        ):
            raise ConfigError(
                f"{label}: line {lineno} of {path} is not valid JSON for an ICL "
                f'example: each line needs an object "input" and a string "output"'
            )
        examples.append(IclExample(input=value["input"], output=value["output"]))
    if not examples:
        raise ConfigError(f"{label}: ICL example file {path} contains no examples")
    return examples


# --------------------------------------------------------------------------
# Input loading and prompt rendering
# --------------------------------------------------------------------------

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


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
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"invalid JSON on line {lineno} of input file {path}: {exc.msg}"
            ) from None
        if not isinstance(value, dict):
            raise ConfigError(
                f"line {lineno} of input file {path} must be a JSON object"
            )
        rows.append(value)
    return rows


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def render_template(
    template: str,
    row: dict,
    row_index: int,
    extra: dict[str, Any] | None = None,
    prefix: str = "",
    source: str = "prompt template",
) -> str:
    def replace(match: re.Match[str]) -> str:
        field_name = match.group(1)
        if extra is not None and field_name in extra:
            return _stringify(extra[field_name])
        if field_name not in row:
            raise ConfigError(
                f"{prefix}row {row_index}: missing field '{field_name}' "
                f"referenced by {source}"
            )
        return _stringify(row[field_name])

    return PLACEHOLDER_RE.sub(replace, template)


def build_messages(
    config: TaskConfig, row: dict, row_index: int, prefix: str = ""
) -> list[dict]:
    messages: list[dict] = []
    if config.system_template is not None:
        messages.append(
            {
                "role": "system",
                "content": render_template(
                    config.system_template, row, row_index, prefix=prefix
                ),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": render_template(
                config.user_template, row, row_index, prefix=prefix
            ),
        }
    )
    return messages


def render_icl_messages(
    examples: list[IclExample], user_template: str, label: str
) -> list[dict]:
    """Render few-shot examples as alternating user/assistant turns.

    Each example input goes through the task's `prompt.user` template; the
    example output is used verbatim as the assistant reply.
    """
    messages: list[dict] = []
    for index, example in enumerate(examples):
        messages.append(
            {
                "role": "user",
                "content": render_template(
                    user_template,
                    example.input,
                    index,
                    prefix=f"{label} example ",
                    source="prompt.user template",
                ),
            }
        )
        messages.append({"role": "assistant", "content": example.output})
    return messages


def with_icl(messages: list[dict], setup: IclSetup | None) -> list[dict]:
    """Insert a setup's example turns between the system and the final user turn."""
    if setup is None or not setup.messages:
        return messages
    return messages[:-1] + list(setup.messages) + messages[-1:]


def select_setup(config: TaskConfig, attempt_index: int) -> IclSetup | None:
    """Pick the ICL setup for one attempt, following the configured strategy."""
    icl = config.icl
    if icl is None:
        return None
    setups = icl.setups
    if config.scheme == "greedy" and config.num_solutions > 1:
        # Greedy is deterministic per setup: walk them in declared order, once each.
        return setups[attempt_index % len(setups)]
    if icl.strategy == "random":
        return random.choice(setups)
    if icl.strategy == "round_robin":
        return setups[attempt_index % len(setups)]
    return setups[0]


# --------------------------------------------------------------------------
# Chat templates (completions mode)
# --------------------------------------------------------------------------

TOOL_CALL_OPEN = "<tool_call>"
TOOL_CALL_CLOSE = "</tool_call>"


def _message_content(message: dict) -> str:
    """The text a template renders for one conversation message."""
    role = message.get("role")
    content = message.get("content")
    text = "" if content is None else str(content)
    if role == "tool":
        payload = {"name": message.get("name"), "content": text}
        return (
            "<tool_response>\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\n</tool_response>"
        )
    if role == "assistant" and not text:
        blocks = _tool_call_blocks(message.get("tool_calls"))
        if blocks:
            return blocks
    return text


def _tool_call_blocks(tool_calls: Any) -> str:
    """Render native tool calls back into <tool_call> text blocks."""
    if not isinstance(tool_calls, list):
        return ""
    blocks = []
    for entry in tool_calls:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function") if isinstance(entry.get("function"), dict) else {}
        name = function.get("name") or entry.get("name") or ""
        arguments = function.get("arguments", entry.get("arguments"))
        args, _ = _parse_tool_arguments(arguments)
        body = json.dumps({"name": name, "arguments": args}, ensure_ascii=False)
        blocks.append(f"{TOOL_CALL_OPEN}\n{body}\n{TOOL_CALL_CLOSE}")
    return "\n".join(blocks)


def _render_chatml(messages: list[dict]) -> str:
    parts = []
    for message in messages:
        role = str(message.get("role") or "user")
        parts.append(f"<|im_start|>{role}\n{_message_content(message)}<|im_end|>\n")
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


def _render_llama3(messages: list[dict]) -> str:
    parts = ["<|begin_of_text|>"]
    for message in messages:
        role = str(message.get("role") or "user")
        parts.append(
            f"<|start_header_id|>{role}<|end_header_id|>\n\n"
            f"{_message_content(message)}<|eot_id|>"
        )
    parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return "".join(parts)


def _render_zephyr(messages: list[dict]) -> str:
    parts = []
    for message in messages:
        role = str(message.get("role") or "user")
        parts.append(f"<|{role}|>\n{_message_content(message)}</s>\n")
    parts.append("<|assistant|>\n")
    return "".join(parts)


def _render_mistral(messages: list[dict]) -> str:
    """Mistral has no system or tool role: both fold into the user instruction."""
    parts: list[str] = []
    system: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        chunks = system + pending
        system.clear()
        pending.clear()
        if chunks:
            parts.append("[INST] " + "\n\n".join(chunks) + " [/INST]")

    for message in messages:
        role = str(message.get("role") or "user")
        text = _message_content(message)
        if role == "system":
            system.append(text)
        elif role == "assistant":
            flush()
            parts.append(" " + text + "</s>")
        else:  # user, tool, anything else
            pending.append(text)
    flush()
    return "".join(parts)


TEMPLATE_RENDERERS = {
    "chatml": _render_chatml,
    "llama3": _render_llama3,
    "mistral": _render_mistral,
    "zephyr": _render_zephyr,
}


def render_chat_prompt(messages: list[dict], template: str | None) -> str:
    """Render a conversation into a single prompt string for /v1/completions."""
    renderer = TEMPLATE_RENDERERS.get(
        (template or DEFAULT_CHAT_TEMPLATE).strip().lower(), _render_chatml
    )
    return renderer(messages)


def render_tool_instructions(tools: list[ToolConfig]) -> str:
    """Describe the available tools and the <tool_call> protocol in the prompt."""
    lines = ["You have access to the following tools:", ""]
    for tool in tools:
        lines.append(json.dumps(tool.definition(), ensure_ascii=False))
    lines += [
        "",
        "To call a tool, reply with one block per call, in this exact form:",
        TOOL_CALL_OPEN,
        '{"name": "<tool name>", "arguments": {<arguments as JSON>}}',
        TOOL_CALL_CLOSE,
        "",
        "Tool results are returned to you in tool messages. When you can answer, "
        "reply with the final answer as plain text and no tool call block.",
    ]
    return "\n".join(lines)


def with_tool_prompt(messages: list[dict], tools: list[ToolConfig]) -> list[dict]:
    """Fold the tool documentation into the system message (completions mode)."""
    if not tools:
        return messages
    instructions = render_tool_instructions(tools)
    conversation = list(messages)
    if conversation and conversation[0].get("role") == "system":
        first = dict(conversation[0])
        content = str(first.get("content") or "")
        first["content"] = f"{content}\n\n{instructions}" if content else instructions
        conversation[0] = first
    else:
        conversation.insert(0, {"role": "system", "content": instructions})
    return conversation


def _template_fields(template: str | None) -> list[str]:
    if not template:
        return []
    names = []
    for match in PLACEHOLDER_RE.finditer(template):
        name = match.group(1)
        if name != RESPONSE_PLACEHOLDER and name not in names:
            names.append(name)
    return names


def prepare_rows(
    config: TaskConfig, rows: list[dict], multi: bool = False
) -> list[list[dict]]:
    """Render every prompt up-front so template/input errors surface before any I/O."""
    prefix = f"task '{config.name}': " if multi else ""
    evaluation = config.evaluation

    answer_field = None
    deferred: list[tuple[str, str]] = []  # (field, source label)
    if evaluation is not None:
        if evaluation.type in ("exact_match", "contains"):
            answer_field = evaluation.answer_field
        elif evaluation.type == "script":
            deferred = [
                (name, "evaluation.command_template")
                for name in _template_fields(evaluation.command_template)
            ]
        elif evaluation.type == "llm_judge":
            names = _template_fields(evaluation.judge_system)
            for name in _template_fields(evaluation.judge_user):
                if name not in names:
                    names.append(name)
            deferred = [(name, "evaluation.judge_prompt") for name in names]

    prepared: list[list[dict]] = []
    for index, row in enumerate(rows):
        prepared.append(build_messages(config, row, index, prefix=prefix))
        if answer_field is not None and answer_field not in row:
            raise ConfigError(
                f"{prefix}row {index}: missing field '{answer_field}' "
                f"required by {'tasks.' + config.name if multi else 'task'}"
                f".evaluation.answer_field"
            )
        for name, source in deferred:
            if name not in row:
                raise ConfigError(
                    f"{prefix}row {index}: missing field '{name}' "
                    f"referenced by {source}"
                )
    return prepared


# --------------------------------------------------------------------------
# Answer extraction and evaluation
# --------------------------------------------------------------------------

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# "Answer: A", "the answer is B)", "option (C)" - the letter itself stays
# case-sensitive, so only uppercase choices are accepted.
LETTER_HINT_RE = re.compile(
    r"(?:[Aa][Nn][Ss][Ww][Ee][Rr]|[Cc][Hh][Oo][Ii][Cc][Ee]|[Oo][Pp][Tt][Ii][Oo][Nn])"
    r"[^A-Za-z0-9]{0,8}(?:[Ii][Ss][^A-Za-z0-9]{0,4})?\(?([A-D])(?![A-Za-z])"
)
# A standalone uppercase A-D: "A", "(A)", "A)", "A."
LETTER_RE = re.compile(r"(?<![A-Za-z])([A-D])(?![A-Za-z])")


def extract_answer(text: str, method: str) -> str | None:
    if text is None:
        return None
    if method == "full":
        return text.strip()
    if method == "last_line":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else None
    if method == "last_number":
        matches = NUMBER_RE.findall(text.replace(",", ""))
        return matches[-1] if matches else None
    if method == "first_number":
        match = NUMBER_RE.search(text.replace(",", ""))
        return match.group(0) if match else None
    if method == "letter":
        hint = LETTER_HINT_RE.search(text)
        if hint is not None:
            return hint.group(1)
        match = LETTER_RE.search(text)
        return match.group(1) if match else None
    return text.strip()


def _to_number(text: Any) -> float | None:
    if text is None:
        return None
    try:
        return float(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _normalize(text: str) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed.strip().strip(".").casefold()


def values_match(extracted: str | None, expected: Any) -> bool:
    if extracted is None:
        return False
    left = str(extracted).strip()
    right = _stringify(expected).strip()
    if left == right:
        return True
    left_number = _to_number(left)
    right_number = _to_number(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return _normalize(left) == _normalize(right)


def _tidy_score(score: float) -> Any:
    return int(score) if float(score).is_integer() else score


@dataclass
class EvalOutcome:
    passed: bool
    extracted: str | None = None
    judge_score: Any = None
    judge_meta: dict | None = None


def evaluate_response(
    evaluation: EvaluationConfig, text: str, row: dict
) -> tuple[bool, str | None]:
    """Return (passed, extracted_answer) for one response (synchronous types)."""
    if evaluation.type == "exact_match":
        extracted = extract_answer(text, evaluation.extract_method)
        expected = row.get(evaluation.answer_field)
        return values_match(extracted, expected), extracted

    if evaluation.type == "contains":
        expected = _stringify(row.get(evaluation.answer_field))
        passed = expected in (text or "")
        if evaluation.extract is not None:
            extracted = extract_answer(text, evaluation.extract_method)
        else:
            extracted = expected if passed else None
        return passed, extracted

    # regex
    match = evaluation.compiled.search(text or "")
    if match is None:
        extracted = (
            extract_answer(text, evaluation.extract_method)
            if evaluation.extract is not None
            else None
        )
        return False, extracted
    if evaluation.extract is not None:
        extracted = extract_answer(text, evaluation.extract_method)
    else:
        extracted = match.group(1) if match.groups() else match.group(0)
    return True, extracted


def render_command(
    evaluation: EvaluationConfig, row: dict, row_index: int, response: str, prefix: str
) -> str:
    command = render_template(
        evaluation.command_template,
        row,
        row_index,
        extra={RESPONSE_PLACEHOLDER: response},
        prefix=prefix,
        source="evaluation.command_template",
    )
    # A row field may itself expand to text containing {__response__}.
    placeholder = "{" + RESPONSE_PLACEHOLDER + "}"
    if placeholder in command:
        command = command.replace(placeholder, response)
    return command


def _kill_process_tree(process: Any) -> None:
    """SIGKILL the timed-out shell and everything it started."""
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError, OSError):
        process.kill()


async def run_script_evaluation(
    evaluation: EvaluationConfig, row: dict, row_index: int, response: str, prefix: str
) -> bool:
    """Run the rendered command in a shell; success_exit_code means pass."""
    command = render_command(evaluation, row, row_index, response, prefix)
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group, so a timeout kills children too
        )
    except (OSError, ValueError):
        return False

    try:
        # stdout/stderr are captured (and discarded) so they never reach the output.
        await asyncio.wait_for(process.communicate(), timeout=SCRIPT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        _kill_process_tree(process)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(process.wait(), timeout=KILL_GRACE_SECONDS)
        return False
    return process.returncode == evaluation.success_exit_code


def build_judge_messages(
    evaluation: EvaluationConfig, row: dict, row_index: int, response: str, prefix: str
) -> list[dict]:
    extra = {RESPONSE_PLACEHOLDER: response}
    messages: list[dict] = []
    if evaluation.judge_system is not None:
        messages.append(
            {
                "role": "system",
                "content": render_template(
                    evaluation.judge_system,
                    row,
                    row_index,
                    extra=extra,
                    prefix=prefix,
                    source="evaluation.judge_prompt.system",
                ),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": render_template(
                evaluation.judge_user,
                row,
                row_index,
                extra=extra,
                prefix=prefix,
                source="evaluation.judge_prompt.user",
            ),
        }
    )
    return messages


async def evaluate_candidate(
    client: httpx.AsyncClient,
    config: TaskConfig,
    row: dict,
    row_index: int,
    response: str,
    ctx: "TaskContext",
    prefix: str = "",
) -> EvalOutcome:
    """Evaluate one generated response; may issue a judge call or run a script."""
    evaluation = config.evaluation
    if evaluation is None:
        return EvalOutcome(passed=True)

    if evaluation.type == "script":
        try:
            passed = await run_script_evaluation(
                evaluation, row, row_index, response, prefix
            )
        except ConfigError:
            passed = False
        extracted = (
            extract_answer(response, evaluation.extract_method)
            if evaluation.extract is not None
            else None
        )
        return EvalOutcome(passed=passed, extracted=extracted)

    if evaluation.type == "llm_judge":
        try:
            messages = build_judge_messages(
                evaluation, row, row_index, response, prefix
            )
        except ConfigError:
            return EvalOutcome(passed=False)
        request = config.api_request(
            messages, model=config.judge_model, temperature=JUDGE_TEMPERATURE
        )
        call = await call_api(client, request, ctx)
        judge_meta = dict(call.meta)
        if not call.ok:
            return EvalOutcome(passed=False, judge_meta=judge_meta)
        extracted = extract_answer(call.content or "", evaluation.extract_method)
        score = _to_number(extracted)
        passed = score is not None and score >= evaluation.threshold
        return EvalOutcome(
            passed=passed,
            extracted=extracted,
            judge_score=None if score is None else _tidy_score(score),
            judge_meta=judge_meta,
        )

    passed, extracted = evaluate_response(evaluation, response, row)
    return EvalOutcome(passed=passed, extracted=extracted)


# --------------------------------------------------------------------------
# Structured output validation (JSON Schema draft 7 subset)
# --------------------------------------------------------------------------


def json_type_name(value: Any) -> str:
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


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and float(value).is_integer()
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _schema_label(path: str) -> str:
    return f"Field '{path}'" if path else "Response"


def _join_path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def validate_schema(value: Any, schema: Any, path: str = "") -> str | None:
    """Return a human-readable error, or None when `value` satisfies `schema`."""
    if not isinstance(schema, dict):
        return None
    label = _schema_label(path)

    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        if not any(_matches_type(value, str(name)) for name in names):
            wanted = " or ".join(str(name) for name in names)
            return (
                f"{label} must be of type {wanted}, got {json_type_name(value)}"
            )

    if "enum" in schema and isinstance(schema["enum"], list):
        if not any(_enum_equal(value, option) for option in schema["enum"]):
            options = ", ".join(json.dumps(option) for option in schema["enum"])
            return f"{label} must be one of [{options}], got {json.dumps(value)}"

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if minimum_length is not None and len(value) < int(minimum_length):
            return (
                f"{label} must be at least {int(minimum_length)} characters, "
                f"got {len(value)}"
            )
        maximum_length = schema.get("maxLength")
        if maximum_length is not None and len(value) > int(maximum_length):
            return (
                f"{label} must be at most {int(maximum_length)} characters, "
                f"got {len(value)}"
            )
        pattern = schema.get("pattern")
        if pattern is not None and re.search(str(pattern), value) is None:
            return f"{label} does not match pattern {str(pattern)!r}"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < float(minimum):
            return f"{label} must be >= {minimum}, got {value}"
        maximum = schema.get("maximum")
        if maximum is not None and value > float(maximum):
            return f"{label} must be <= {maximum}, got {value}"

    if isinstance(value, dict):
        required = schema.get("required")
        if isinstance(required, list):
            for name in required:
                if name not in value:
                    missing = _join_path(path, str(name))
                    return f"Missing required field: {missing}"
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, subschema in properties.items():
                if key in value:
                    error = validate_schema(
                        value[key], subschema, _join_path(path, str(key))
                    )
                    if error is not None:
                        return error

    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, list):
            for index, subschema in enumerate(items):
                if index < len(value):
                    error = validate_schema(
                        value[index], subschema, f"{path}[{index}]" if path else f"[{index}]"
                    )
                    if error is not None:
                        return error
        elif isinstance(items, dict):
            for index, entry in enumerate(value):
                error = validate_schema(
                    entry, items, f"{path}[{index}]" if path else f"[{index}]"
                )
                if error is not None:
                    return error

    return None


def _enum_equal(value: Any, option: Any) -> bool:
    if isinstance(value, bool) != isinstance(option, bool):
        return False
    if isinstance(value, (int, float)) and isinstance(option, (int, float)):
        return float(value) == float(option)
    return value == option


@dataclass
class SchemaOutcome:
    valid: bool
    value: Any = None
    error: str | None = None


def check_output_schema(config: TaskConfig, text: str | None) -> SchemaOutcome | None:
    """Parse and validate a response against the task's `output_schema`."""
    if config.output_schema is None:
        return None
    if text is None:
        return SchemaOutcome(False, None, "Response is empty and is not valid JSON")
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        detail = getattr(exc, "msg", str(exc))
        return SchemaOutcome(False, None, f"Response is not valid JSON: {detail}")
    error = validate_schema(parsed, config.output_schema)
    if error is not None:
        return SchemaOutcome(False, None, error)
    return SchemaOutcome(True, parsed, None)


# --------------------------------------------------------------------------
# Tool calls (agentic generation)
# --------------------------------------------------------------------------

# A tool call written into the response text (completions mode, and as a
# fallback in chat mode): <tool_call>{"name": ..., "arguments": {...}}</tool_call>
TOOL_CALL_BLOCK_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)
TOOL_CALL_TAIL_RE = re.compile(r"<tool_call>\s*(.+)\Z", re.S)


@dataclass
class ToolCall:
    """One tool invocation requested by the model."""

    name: str
    args: dict
    id: str | None = None
    raw: dict | None = None  # native OpenAI shape, echoed back to the model
    error: str | None = None  # set when the request itself could not be parsed


def _parse_tool_arguments(value: Any) -> tuple[dict, str | None]:
    """`function.arguments` is JSON text; accept a mapping as well."""
    if value is None or value == "":
        return {}, None
    if isinstance(value, dict):
        return dict(value), None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}, f"could not parse tool arguments as JSON: {value!r}"
        if isinstance(parsed, dict):
            return parsed, None
        return {}, "tool arguments were not a JSON object"
    return {}, "tool arguments were not a JSON object"


def native_tool_calls(message: Any) -> list[ToolCall]:
    """Read `message.tool_calls` from a chat completion choice."""
    if not isinstance(message, dict):
        return []
    entries = message.get("tool_calls")
    if not isinstance(entries, list) or not entries:
        return []
    calls: list[ToolCall] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        function = entry.get("function") if isinstance(entry.get("function"), dict) else {}
        name = function.get("name") or entry.get("name") or ""
        args, error = _parse_tool_arguments(function.get("arguments", entry.get("arguments")))
        calls.append(
            ToolCall(
                name=str(name),
                args=args,
                id=str(entry.get("id")) if entry.get("id") is not None else f"call_{index}",
                raw=entry,
                error=error,
            )
        )
    return calls


def parse_text_tool_calls(text: str | None) -> list[ToolCall]:
    """Read <tool_call> blocks out of a plain-text response."""
    if not text or TOOL_CALL_OPEN not in text:
        return []
    blocks = TOOL_CALL_BLOCK_RE.findall(text)
    if not blocks:
        tail = TOOL_CALL_TAIL_RE.search(text)
        blocks = [tail.group(1)] if tail is not None else []

    calls: list[ToolCall] = []
    for index, block in enumerate(blocks, start=1):
        body = block.strip().strip("`").strip()
        error = None
        name = ""
        args: dict = {}
        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
            error = f"could not parse tool call as JSON: {body!r}"
        if isinstance(payload, dict):
            name = str(payload.get("name") or payload.get("tool") or "")
            args, error = _parse_tool_arguments(
                payload.get("arguments", payload.get("args"))
            )
        elif error is None:
            error = "tool call was not a JSON object"
        calls.append(
            ToolCall(name=name, args=args, id=f"call_{index}", raw=None, error=error)
        )
    return calls


def _static_map_key(tool: ToolConfig, args: dict) -> str | None:
    """The first required parameter of a tool, used as the static_map lookup key."""
    parameters = tool.parameters if isinstance(tool.parameters, dict) else {}
    properties = parameters.get("properties")
    properties = properties if isinstance(properties, dict) else {}

    required = parameters.get("required")
    if not isinstance(required, list) or not required:
        # Tolerate `required` nested one level too deep, inside `properties`.
        nested = properties.get("required")
        required = nested if isinstance(nested, list) else None
    if isinstance(required, list) and required:
        return str(required[0])
    for key in properties:
        if key != "required":
            return str(key)
    for key in args:
        return str(key)
    return None


async def run_script_tool(handler: ToolHandler, args: dict) -> str:
    """Run `command` with the `arg_field` value as a single argument."""
    if handler.arg_field not in args:
        return f"ERROR: missing tool argument '{handler.arg_field}'"
    value = _stringify(args[handler.arg_field])
    try:
        argv = shlex.split(handler.command or "")
    except ValueError:
        argv = (handler.command or "").split()
    if not argv:
        return "ERROR: tool handler command is empty"

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            value,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own group, so a timeout kills children too
        )
    except (OSError, ValueError) as exc:
        return f"ERROR: {exc}"

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=TOOL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        _kill_process_tree(process)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(process.wait(), timeout=KILL_GRACE_SECONDS)
        return f"ERROR: command timed out after {TOOL_TIMEOUT_SECONDS:g} seconds"

    if process.returncode != 0:
        detail = (stderr or b"").decode("utf-8", "replace").strip()
        return "ERROR: " + (
            detail or f"command exited with status {process.returncode}"
        )
    return (stdout or b"").decode("utf-8", "replace").strip()


async def run_tool(tool: ToolConfig, args: dict) -> str:
    handler = tool.handler
    if handler.type == "echo":
        return json.dumps(args, ensure_ascii=False)
    if handler.type == "static_map":
        key = _static_map_key(tool, args)
        if key is None or key not in args:
            return handler.default
        return handler.mapping.get(_stringify(args[key]), handler.default)
    return await run_script_tool(handler, args)


async def execute_tool_call(config: TaskConfig, call: ToolCall) -> str:
    """Invoke one tool; handler problems come back as an "ERROR: ..." result."""
    if call.error is not None:
        return f"ERROR: {call.error}"
    tool = config.tool_by_name(call.name)
    if tool is None:
        return f"ERROR: unknown tool '{call.name}'"
    try:
        return await run_tool(tool, call.args)
    except Exception as exc:  # a broken handler must not break the loop
        return f"ERROR: {type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# Token-aware scheduling, cost accounting and progress
# --------------------------------------------------------------------------


class BudgetExceeded(Exception):
    """Raised instead of dispatching once the cost budget is spent."""


def count_words(text: Any) -> int:
    return len(str(text or "").split())


def estimate_prompt_tokens(messages: list[dict]) -> int:
    """`1 token ~= 0.75 words`, rounded up, over the rendered messages."""
    words = 0
    for message in messages or []:
        if isinstance(message, dict):
            words += count_words(_message_content(message))
            words += count_words(message.get("name"))
        else:
            words += count_words(message)
    return int(math.ceil(words / WORDS_PER_TOKEN)) if words else 0


@dataclass
class TokenReservation:
    at: float
    tokens: int


class RateLimiter:
    """Sliding 60-second RPM and TPM windows plus a hard concurrency cap.

    Requests are admitted through a single FIFO gate, so a task's rows still
    reach the wire in input order even while many of them are in flight.
    """

    def __init__(
        self,
        rpm: int | None = None,
        tpm: int | None = None,
        max_concurrent: int | None = None,
    ) -> None:
        self.rpm = rpm
        self.tpm = tpm
        self.max_concurrent = max_concurrent
        self._semaphore = (
            asyncio.Semaphore(max_concurrent) if max_concurrent else None
        )
        self._gate = asyncio.Lock()
        self._requests: deque[float] = deque()
        self._tokens: deque[TokenReservation] = deque()
        # Set whenever a reservation shrinks to the usage actually reported, so
        # a waiter does not sleep out the whole window for capacity it has.
        self._released = asyncio.Event()

    @property
    def limited(self) -> bool:
        return self.rpm is not None or self.tpm is not None

    def _prune(self, now: float) -> None:
        cutoff = now - RATE_WINDOW_SECONDS
        while self._requests and self._requests[0] <= cutoff:
            self._requests.popleft()
        while self._tokens and self._tokens[0].at <= cutoff:
            self._tokens.popleft()

    def _token_total(self) -> int:
        return sum(entry.tokens for entry in self._tokens)

    async def acquire(self, estimated_tokens: int = 0) -> TokenReservation | None:
        """Wait until both budgets have room, then reserve a request slot."""
        if not self.limited:
            return None
        async with self._gate:
            while True:
                now = time.monotonic()
                self._prune(now)
                waits: list[float] = []
                if self.rpm is not None and len(self._requests) >= self.rpm:
                    waits.append(self._requests[0] + RATE_WINDOW_SECONDS - now)
                if self.tpm is not None and self._tokens:
                    used = self._token_total()
                    if used + estimated_tokens > self.tpm:
                        waits.append(self._tokens[0].at + RATE_WINDOW_SECONDS - now)
                if not waits:
                    if self.rpm is not None:
                        self._requests.append(now)
                    if self.tpm is None:
                        return None
                    reservation = TokenReservation(now, estimated_tokens)
                    self._tokens.append(reservation)
                    return reservation
                delay = max(min(waits), MIN_LIMITER_SLEEP)
                self._released.clear()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._released.wait(), timeout=delay)

    def record_usage(
        self, reservation: TokenReservation | None, prompt_tokens: int, completion_tokens: int
    ) -> None:
        """Replace an estimate with the usage the API actually reported."""
        if reservation is None:
            return
        actual = max(0, int(prompt_tokens) + int(completion_tokens))
        freed = actual < reservation.tokens
        reservation.tokens = actual
        if freed:
            self._released.set()

    @contextlib.asynccontextmanager
    async def slot(self):
        """Hold one of `max_concurrent` in-flight slots."""
        if self._semaphore is None:
            yield
            return
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()


@dataclass
class CostTracker:
    """Run-wide cost accounting; `budget` stops new requests when reached."""

    enabled: bool = False
    budget: float | None = None
    prompt: float = 0.0
    completion: float = 0.0
    exceeded: bool = False

    @property
    def total(self) -> float:
        return self.prompt + self.completion

    def add(self, prompt_cost: float, completion_cost: float) -> None:
        self.prompt += prompt_cost
        self.completion += completion_cost
        if self.budget is not None and self.total >= self.budget:
            self.exceeded = True

    def out_of_budget(self) -> bool:
        if self.budget is None:
            return False
        if self.total >= self.budget:
            self.exceeded = True
        return self.exceeded

    def summary(self) -> dict:
        entry: dict[str, Any] = {
            "total": round(self.total, COST_DECIMALS),
            "prompt": round(self.prompt, COST_DECIMALS),
            "completion": round(self.completion, COST_DECIMALS),
            "budget": None if self.budget is None else self.budget,
            "budget_remaining": (
                None
                if self.budget is None
                else round(max(0.0, self.budget - self.total), COST_DECIMALS)
            ),
            "budget_exceeded": bool(self.exceeded),
        }
        return entry


class ProgressReporter:
    """`--progress`: a stderr line every 5s or every 10% of the inputs."""

    def __init__(self, total: int, *, show_eval: bool, show_cost: bool,
                 stats: "Stats", cost: CostTracker) -> None:
        self.total = total
        self.show_eval = show_eval
        self.show_cost = show_cost
        self.stats = stats
        self.cost = cost
        self.completed = 0
        self.passed = 0
        self.failed = 0
        self.started = time.monotonic()
        self._last_print = self.started
        self._last_count = 0
        self._step = max(1, int(math.ceil(total * PROGRESS_FRACTION))) if total else 1

    def record_row(self, result: dict | None) -> None:
        self.completed += 1
        if result is not None:
            passed, failed = _count_results([result])
            self.passed += passed
            self.failed += failed
        if self.completed - self._last_count >= self._step or self.completed >= self.total:
            self.emit()

    def maybe_emit(self) -> None:
        if time.monotonic() - self._last_print >= PROGRESS_INTERVAL_SECONDS:
            self.emit()

    def emit(self) -> None:
        now = time.monotonic()
        self._last_print = now
        self._last_count = self.completed
        print(self.line(now), file=sys.stderr, flush=True)

    def line(self, now: float | None = None) -> str:
        now = time.monotonic() if now is None else now
        elapsed = max(1e-9, now - self.started)
        percent = int(self.completed / self.total * 100) if self.total else 100
        parts = [f"[{self.completed}/{self.total}] {percent}% complete"]
        if self.show_eval:
            parts.append(f"{self.passed} passed, {self.failed} failed")
        rate = self.stats.total_api_calls / elapsed * 60.0
        parts.append(f"{rate:.1f} rpm")
        if self.show_cost:
            parts.append(f"${self.cost.total:.2f} spent")
        if self.completed > 0 and self.completed < self.total:
            remaining = (self.total - self.completed) * (elapsed / self.completed)
            parts.append(f"ETA: {int(round(remaining))}s")
        elif self.completed >= self.total:
            parts.append("ETA: 0s")
        else:
            parts.append("ETA: ?")
        return " | ".join(parts)


@dataclass
class TaskContext:
    """Everything one task's row handlers need beyond its config."""

    config: TaskConfig
    stats: "Stats"
    limiter: RateLimiter
    cost: CostTracker
    progress: ProgressReporter | None = None

    def charge(self, prompt_tokens: int, completion_tokens: int) -> None:
        if self.config.cost is None:
            return
        prompt_cost, completion_cost = self.config.cost.call_cost(
            prompt_tokens, completion_tokens
        )
        self.cost.add(prompt_cost, completion_cost)

    def check_budget(self) -> None:
        if self.cost.out_of_budget():
            raise BudgetExceeded()


# --------------------------------------------------------------------------
# API calls
# --------------------------------------------------------------------------


@dataclass
class Stats:
    total_api_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    first_request_at: float | None = None
    last_response_at: float | None = None
    parent: Any = None

    def count_call(self, moment: float) -> None:
        self.total_api_calls += 1
        self.mark_start(moment)
        if self.parent is not None:
            self.parent.count_call(moment)

    def add_tokens(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        if self.parent is not None:
            self.parent.add_tokens(prompt, completion)

    def mark_start(self, moment: float) -> None:
        if self.first_request_at is None or moment < self.first_request_at:
            self.first_request_at = moment

    def mark_end(self, moment: float) -> None:
        if self.last_response_at is None or moment > self.last_response_at:
            self.last_response_at = moment
        if self.parent is not None:
            self.parent.mark_end(moment)


@dataclass
class ApiRequest:
    endpoint: str
    model: str
    temperature: float
    max_tokens: int
    messages: list[dict]
    api_type: str = DEFAULT_API_TYPE
    chat_template: str = DEFAULT_CHAT_TEMPLATE
    tools: list[dict] | None = None

    def payload(self) -> dict:
        """The JSON body: a messages array, or a rendered prompt string."""
        if self.api_type == "completions":
            return {
                "model": self.model,
                "prompt": render_chat_prompt(self.messages, self.chat_template),
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.tools:
            body["tools"] = self.tools
        return body


@dataclass
class CallResult:
    ok: bool
    content: str | None = None
    meta: dict = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)


def _usage_int(usage: Any, key: str) -> int:
    if isinstance(usage, dict):
        value = usage.get(key)
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return int(value)
    return 0


async def call_api(
    client: httpx.AsyncClient,
    request: ApiRequest,
    ctx: "TaskContext",
    *,
    hold_slot: bool = True,
) -> CallResult:
    """One logical attempt, holding a concurrency slot unless the caller has one."""
    if not hold_slot:
        return await _call_api(client, request, ctx)
    async with ctx.limiter.slot():
        return await _call_api(client, request, ctx)


async def _call_api(
    client: httpx.AsyncClient, request: ApiRequest, ctx: "TaskContext"
) -> CallResult:
    """Up to MAX_HTTP_ATTEMPTS HTTP requests on 5xx/transport errors.

    Every HTTP request passes the task's RPM/TPM windows first: the prompt is
    estimated from the rendered messages and reserved together with
    `max_tokens`, and that reservation is replaced by the usage the API reports.
    """
    stats = ctx.stats
    payload = request.payload()
    estimate = estimate_prompt_tokens(request.messages) + request.max_tokens
    last_error = "request failed"
    last_latency = 0

    for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
        ctx.check_budget()
        reservation = await ctx.limiter.acquire(estimate)
        started = time.monotonic()
        stats.count_call(started)
        retryable = False
        try:
            response = await client.post(request.endpoint, json=payload)
            finished = time.monotonic()
            stats.mark_end(finished)
            last_latency = int(round((finished - started) * 1000))

            if response.status_code >= 500:
                retryable = True
                last_error = f"HTTP {response.status_code} from API"
            elif response.status_code >= 400:
                last_error = f"HTTP {response.status_code} from API"
            else:
                try:
                    body = response.json()
                except ValueError:
                    last_error = "API response was not valid JSON"
                    body = None
                if body is not None:
                    parsed = _parse_completion(body)
                    if parsed is None:
                        last_error = "API response did not contain a message choice"
                    else:
                        content, finish_reason, usage, tool_calls = parsed
                        prompt_tokens = _usage_int(usage, "prompt_tokens")
                        completion_tokens = _usage_int(usage, "completion_tokens")
                        stats.add_tokens(prompt_tokens, completion_tokens)
                        ctx.limiter.record_usage(
                            reservation, prompt_tokens, completion_tokens
                        )
                        ctx.charge(prompt_tokens, completion_tokens)
                        return CallResult(
                            ok=True,
                            content=content,
                            tool_calls=tool_calls,
                            meta={
                                "model": request.model,
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": _usage_int(usage, "total_tokens")
                                or (prompt_tokens + completion_tokens),
                                "latency_ms": last_latency,
                                "finish_reason": finish_reason,
                            },
                        )
        except httpx.HTTPError as exc:
            finished = time.monotonic()
            stats.mark_end(finished)
            last_latency = int(round((finished - started) * 1000))
            retryable = True
            last_error = f"{type(exc).__name__}: {exc}"

        # Nothing was billed for this request; give the reservation back.
        ctx.limiter.record_usage(reservation, 0, 0)
        if not retryable or attempt == MAX_HTTP_ATTEMPTS:
            break
        await asyncio.sleep(
            RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
        )

    return CallResult(
        ok=False,
        content=None,
        meta={
            "model": request.model,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_ms": last_latency,
            "finish_reason": None,
            "error": last_error,
        },
    )


def _parse_completion(body: Any) -> tuple[str | None, Any, Any, list[ToolCall]] | None:
    """Pull (content, finish_reason, usage, tool_calls) out of a response body.

    Chat responses carry `choices[].message`, completions ones `choices[].text`.
    A chat message may have no content at all when it only requests tools.
    """
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    message = choice.get("message")
    content: Any = None
    if isinstance(message, dict):
        content = message.get("content")
    if content is None:
        content = choice.get("text")
    tool_calls = native_tool_calls(message)
    if content is None and not tool_calls:
        return None
    return (
        None if content is None else str(content),
        choice.get("finish_reason"),
        body.get("usage"),
        tool_calls,
    )


# --------------------------------------------------------------------------
# Agentic generation
# --------------------------------------------------------------------------


@dataclass
class AgenticOutcome:
    """The result of one agentic loop: its final text plus loop bookkeeping."""

    text: str | None = None
    iterations: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)
    finish_reason: Any = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    failed: bool = False  # hard API failure after retries
    error: str | None = None

    @property
    def hit_limit(self) -> bool:
        return self.finish_reason == MAX_ITERATIONS_REASON

    def meta(self) -> dict:
        """Aggregated metadata for the whole loop."""
        meta: dict[str, Any] = {
            "total_prompt_tokens": self.prompt_tokens,
            "total_completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "iterations_detail": self.details,
        }
        if self.error is not None:
            meta["error"] = self.error
        return meta


def assistant_tool_message(call: CallResult, calls: list[ToolCall]) -> dict:
    """The assistant turn that requested tools, appended to the conversation."""
    message: dict[str, Any] = {"role": "assistant", "content": call.content}
    raw = [tool_call.raw for tool_call in calls if tool_call.raw is not None]
    if raw:
        message["tool_calls"] = raw
    return message


def tool_result_message(call: ToolCall, result: str) -> dict:
    message: dict[str, Any] = {"role": "tool", "name": call.name, "content": result}
    if call.id:
        message["tool_call_id"] = call.id
    return message


async def run_agentic_loop(
    client: httpx.AsyncClient,
    config: TaskConfig,
    messages: list[dict],
    ctx: "TaskContext",
) -> AgenticOutcome:
    """Call the model repeatedly, running requested tools, until it answers.

    Every API request counts as one iteration. The loop stops on a response
    that carries final text and no tool calls, on a hard API failure, or once
    `max_iterations` requests have been made (`finish_reason: max_iterations`).
    """
    conversation = list(messages)
    if config.api_type == "completions":
        # No native `tools` field: document the tools inside the prompt instead.
        conversation = with_tool_prompt(conversation, config.tools)
    tools_payload = config.tool_definitions() if config.api_type == "chat" else None

    outcome = AgenticOutcome()
    started = time.monotonic()
    while outcome.iterations < config.max_iterations:
        call = await call_api(
            client,
            config.api_request(conversation, tools=tools_payload),
            ctx,
            hold_slot=False,  # the loop already holds one concurrency slot
        )
        outcome.iterations += 1

        detail = {
            "prompt_tokens": _usage_int(call.meta, "prompt_tokens"),
            "completion_tokens": _usage_int(call.meta, "completion_tokens"),
            "total_tokens": _usage_int(call.meta, "total_tokens"),
            "latency_ms": call.meta.get("latency_ms", 0),
            "finish_reason": call.meta.get("finish_reason"),
        }
        if call.meta.get("error") is not None:
            detail["error"] = call.meta["error"]
        outcome.details.append(detail)
        outcome.prompt_tokens += detail["prompt_tokens"]
        outcome.completion_tokens += detail["completion_tokens"]
        outcome.total_tokens += detail["total_tokens"]

        if not call.ok:
            outcome.failed = True
            outcome.error = call.meta.get("error")
            break

        calls = call.tool_calls or parse_text_tool_calls(call.content)
        if not calls:
            outcome.text = call.content
            outcome.finish_reason = call.meta.get("finish_reason") or "stop"
            break

        conversation = conversation + [assistant_tool_message(call, calls)]
        for tool_call in calls:
            result = await execute_tool_call(config, tool_call)
            outcome.tool_calls.append(
                {
                    "iteration": outcome.iterations,
                    "tool": tool_call.name,
                    "args": tool_call.args,
                    "result": result,
                }
            )
            conversation.append(tool_result_message(tool_call, result))
    else:
        # The budget ran out before the model produced a final answer.
        outcome.finish_reason = MAX_ITERATIONS_REASON

    outcome.latency_ms = int(round((time.monotonic() - started) * 1000))
    return outcome


async def process_row_agentic(
    client: httpx.AsyncClient,
    config: TaskConfig,
    row: dict,
    row_index: int,
    messages: list[dict],
    ctx: "TaskContext",
    prefix: str = "",
) -> dict:
    """One agentic loop for one row, in the single-solution output shape."""
    evaluation = config.evaluation
    async with ctx.limiter.slot():  # the loop holds one slot for its lifetime
        outcome = await run_agentic_loop(client, config, messages, ctx)
    text = outcome.text

    passed: bool | None = None
    extracted: str | None = None
    judge_score: Any = None
    judge_meta: dict | None = None
    schema_valid: bool | None = None if config.output_schema is None else True
    schema_error: str | None = None
    has_output = False
    output_value: Any = None

    if text is None:
        # No final answer: a hit iteration limit always fails, and so does a
        # hard API failure once an evaluation or a schema is configured.
        passed = False if (outcome.hit_limit or config.gates_output) else None
        if config.output_schema is not None:
            schema_valid = False
            schema_error = outcome.error or "the loop produced no final answer"
    else:
        schema = check_output_schema(config, text)
        if schema is not None and not schema.valid:
            schema_valid = False
            schema_error = schema.error
            passed = False
        else:
            has_output = True
            output_value = schema.value if schema is not None else text
            if schema is not None:
                schema_valid = True
            if evaluation is not None:
                eval_outcome = await evaluate_candidate(
                    client, config, row, row_index, text, ctx, prefix
                )
                passed = eval_outcome.passed
                extracted = eval_outcome.extracted
                judge_score = eval_outcome.judge_score
                judge_meta = eval_outcome.judge_meta
            elif schema is not None:
                passed = True

    result: dict[str, Any] = {"passed": passed, "extracted_answer": extracted}
    if evaluation is not None and evaluation.type == "llm_judge":
        result["judge_score"] = judge_score
    result["attempts"] = 1
    result["iterations"] = outcome.iterations
    result["tool_calls"] = outcome.tool_calls
    if config.output_schema is not None:
        result["schema_valid"] = bool(schema_valid)
        if not schema_valid:
            result["schema_error"] = schema_error

    meta = outcome.meta()
    if judge_meta is not None:
        meta["judge_meta"] = judge_meta

    return {
        "input": row,
        "output": {config.output_field: output_value} if has_output else None,
        "result": result,
        "meta": meta,
    }


async def process_row_agentic_multi(
    client: httpx.AsyncClient,
    config: TaskConfig,
    row: dict,
    row_index: int,
    messages: list[dict],
    ctx: "TaskContext",
    prefix: str = "",
) -> dict:
    """Several independent agentic loops for one row (ICL / multi-solution).

    Each loop is one attempt and contributes one `meta` entry holding that
    loop's aggregated token usage, latency, finish reason and per-iteration
    detail. A loop that never reaches a usable final answer emits no output.
    """
    evaluation = config.evaluation
    outputs: list[dict] = []
    metas: list[dict] = []
    attempts = 0
    passed_count = 0

    for index in range(config.attempt_budget):
        setup = select_setup(config, index)
        setup_name = setup.name if setup is not None else None
        attempts += 1

        async with ctx.limiter.slot():
            outcome = await run_agentic_loop(
                client, config, with_icl(messages, setup), ctx
            )
        meta = outcome.meta()
        meta["icl_setup"] = setup_name
        text = outcome.text

        usable = text is not None
        value: Any = text
        if usable:
            schema = check_output_schema(config, text)
            if schema is not None:
                meta["schema_valid"] = schema.valid
                if schema.valid:
                    value = schema.value
                else:
                    meta["schema_error"] = schema.error
                    usable = False

        passed: bool | None = None
        if evaluation is not None:
            if not usable:
                passed = False
            else:
                eval_outcome = await evaluate_candidate(
                    client, config, row, row_index, text, ctx, prefix
                )
                passed = eval_outcome.passed
                if eval_outcome.judge_meta is not None:
                    meta["judge_meta"] = eval_outcome.judge_meta
        elif config.output_schema is not None:
            passed = usable
        meta["evaluation_passed"] = passed
        metas.append(meta)

        if passed:
            passed_count += 1
        if usable:
            outputs.append({config.output_field: value, "icl_setup": setup_name})
        if outcome.failed:
            # Hard API failure after retries: stop collecting for this row.
            break

    if evaluation is None:
        result_passed = len(outputs)
        result_failed = attempts - len(outputs)
    else:
        result_passed = passed_count
        result_failed = attempts - passed_count

    return {
        "input": row,
        "output": outputs,
        "result": {
            "passed": result_passed,
            "failed": result_failed,
            "attempts": attempts,
        },
        "meta": metas,
    }


# --------------------------------------------------------------------------
# Row processing
# --------------------------------------------------------------------------


async def process_row(
    client: httpx.AsyncClient,
    config: TaskConfig,
    row: dict,
    row_index: int,
    messages: list[dict],
    ctx: "TaskContext",
    prefix: str = "",
) -> dict:
    evaluation = config.evaluation
    metas: list[dict] = []
    attempts = 0
    has_output = False
    output_value: Any = None
    passed: bool | None = None
    extracted: str | None = None
    judge_score: Any = None
    schema_valid: bool | None = None if config.output_schema is None else True
    schema_error: str | None = None

    request = config.api_request(messages)

    for _ in range(config.max_attempts):
        attempts += 1
        call = await call_api(client, request, ctx)
        meta = dict(call.meta)
        metas.append(meta)

        if not call.ok:
            # Hard failure after retries: the row fails and we stop here.
            has_output = False
            output_value = None
            passed = False if config.gates_output else None
            extracted = None
            judge_score = None
            if config.output_schema is not None:
                schema_valid = False
                schema_error = call.meta.get("error") or "no response from the API"
            break

        # Structured output is validated before any evaluation runs.
        schema = check_output_schema(config, call.content)
        if schema is not None and not schema.valid:
            has_output = False
            output_value = None
            passed = False
            extracted = None
            judge_score = None
            schema_valid = False
            schema_error = schema.error
            if config.scheme == "rejection":
                continue  # a rejected attempt; try again if the budget remains
            break

        if schema is not None:
            schema_valid = True
            schema_error = None
        candidate = schema.value if schema is not None else call.content

        if evaluation is None:
            has_output = True
            output_value = candidate
            # With only a schema configured, validating is what passing means.
            passed = True if schema is not None else None
            break

        outcome = await evaluate_candidate(
            client, config, row, row_index, call.content or "", ctx, prefix
        )
        if outcome.judge_meta is not None:
            meta["judge_meta"] = outcome.judge_meta

        if config.scheme != "rejection" or outcome.passed:
            has_output = True
            output_value = candidate
            passed = outcome.passed
            extracted = outcome.extracted
            judge_score = outcome.judge_score
            break

        # Rejected: discard this candidate and try again (if budget remains).
        has_output = False
        output_value = None
        passed = False
        extracted = None
        judge_score = None

    meta_out: Any = metas[0] if len(metas) == 1 else metas

    result: dict[str, Any] = {
        "passed": passed,
        "extracted_answer": extracted if has_output else None,
    }
    if evaluation is not None and evaluation.type == "llm_judge":
        result["judge_score"] = judge_score if has_output else None
    result["attempts"] = attempts
    if config.output_schema is not None:
        result["schema_valid"] = bool(schema_valid)
        if not schema_valid:
            result["schema_error"] = schema_error

    return {
        "input": row,
        "output": {config.output_field: output_value} if has_output else None,
        "result": result,
        "meta": meta_out,
    }


async def process_row_multi(
    client: httpx.AsyncClient,
    config: TaskConfig,
    row: dict,
    row_index: int,
    messages: list[dict],
    ctx: "TaskContext",
    prefix: str = "",
) -> dict:
    """Collect up to `num_solutions` solutions for one row (ICL / multi-solution).

    greedy   - one attempt per ICL setup, in declared order, at most once each.
    sample   - one sampled attempt per requested solution; evaluation does not
               gate whether the solution is kept.
    rejection- keep generating until `num_solutions` attempts pass or the
               attempt budget runs out; only passing attempts are kept.
    """
    evaluation = config.evaluation
    budget = config.attempt_budget

    outputs: list[dict] = []
    metas: list[dict] = []
    attempts = 0
    passed_count = 0

    while attempts < budget:
        if config.scheme == "rejection" and passed_count >= config.num_solutions:
            break

        setup = select_setup(config, attempts)
        setup_name = setup.name if setup is not None else None
        attempts += 1

        request = config.api_request(with_icl(messages, setup))
        call = await call_api(client, request, ctx)
        meta = dict(call.meta)
        meta["icl_setup"] = setup_name

        if not call.ok:
            # Hard failure after retries: this attempt yields nothing and we stop.
            meta["evaluation_passed"] = False if config.gates_output else None
            metas.append(meta)
            break

        # Structured output is validated before any evaluation runs.
        usable = True
        value: Any = call.content
        schema = check_output_schema(config, call.content)
        if schema is not None:
            meta["schema_valid"] = schema.valid
            if schema.valid:
                value = schema.value
            else:
                meta["schema_error"] = schema.error
                usable = False

        passed: bool | None = None
        if evaluation is not None:
            if usable:
                outcome = await evaluate_candidate(
                    client, config, row, row_index, call.content or "", ctx, prefix
                )
                passed = outcome.passed
                if outcome.judge_meta is not None:
                    meta["judge_meta"] = outcome.judge_meta
            else:
                passed = False
        elif schema is not None:
            passed = usable
        meta["evaluation_passed"] = passed
        metas.append(meta)

        if passed:
            passed_count += 1
        if usable and (config.scheme != "rejection" or passed):
            outputs.append({config.output_field: value, "icl_setup": setup_name})

    if evaluation is None:
        result_passed = len(outputs)
        result_failed = attempts - len(outputs)
    else:
        result_passed = passed_count
        result_failed = attempts - passed_count

    return {
        "input": row,
        "output": outputs,
        "result": {
            "passed": result_passed,
            "failed": result_failed,
            "attempts": attempts,
        },
        "meta": metas,
    }


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------


@dataclass
class TaskRun:
    config: TaskConfig
    input_path: str
    output_path: str
    rows: list[dict] = field(default_factory=list)
    prepared: list[list[dict]] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)
    all_rows: list[dict] = field(default_factory=list)  # before --resume trimming
    resumed_from: int = 0
    kept: list[str] = field(default_factory=list)  # existing output lines to keep

    @property
    def name(self) -> str:
        return self.config.name


def select_row_handler(config: TaskConfig) -> Any:
    """Pick the per-row coroutine for a task's scheme and output shape."""
    if config.scheme == "agentic":
        return process_row_agentic if config.legacy else process_row_agentic_multi
    return process_row if config.legacy else process_row_multi


def compute_concurrency(runs: list[TaskRun], work_count: int) -> int:
    if work_count <= 0:
        return 1
    target = sum(run.config.effective_rpm for run in runs if run.rows)
    target = max(target, MIN_CONCURRENCY)
    cap = 0
    for run in runs:
        if not run.rows:
            continue
        if run.config.max_concurrent is None:
            cap = MAX_CONCURRENCY
            break
        cap += run.config.max_concurrent
    if cap:
        target = min(target, cap)
    return max(1, min(target, MAX_CONCURRENCY, work_count))


def work_order(runs: list[TaskRun]) -> list[tuple[int, int]]:
    """Round-robin over tasks, keeping each task's rows in input order."""
    order: list[tuple[int, int]] = []
    longest = max((len(run.rows) for run in runs), default=0)
    for row_index in range(longest):
        for task_index, run in enumerate(runs):
            if row_index < len(run.rows):
                order.append((task_index, row_index))
    return order


def resolve_budget(runs: list[TaskRun]) -> float | None:
    """The run-wide budget: the tightest one any selected task configured."""
    budgets = [
        run.config.cost.budget
        for run in runs
        if run.config.cost is not None and run.config.cost.budget is not None
    ]
    return min(budgets) if budgets else None


def cost_configured(runs: list[TaskRun]) -> bool:
    return any(run.config.cost is not None for run in runs)


def evaluation_configured(runs: list[TaskRun]) -> bool:
    return any(run.config.gates_output for run in runs)


async def run_all(
    runs: list[TaskRun],
    multi: bool = False,
    *,
    cost: CostTracker | None = None,
    show_progress: bool = False,
) -> Stats:
    global_stats = Stats()
    for run in runs:
        run.stats.parent = global_stats
        run.results = [None] * len(run.rows)  # type: ignore[list-item]

    cost = cost if cost is not None else CostTracker()
    work = work_order(runs)
    if not work:
        return global_stats

    progress = None
    if show_progress:
        progress = ProgressReporter(
            len(work),
            show_eval=evaluation_configured(runs),
            show_cost=cost.enabled,
            stats=global_stats,
            cost=cost,
        )

    contexts = [
        TaskContext(
            config=run.config,
            stats=run.stats,
            limiter=RateLimiter(
                rpm=run.config.rpm,
                tpm=run.config.tpm,
                max_concurrent=run.config.max_concurrent,
            ),
            cost=cost,
            progress=progress,
        )
        for run in runs
    ]

    concurrency = compute_concurrency(runs, len(work))
    queue: asyncio.Queue[tuple[int, int]] = asyncio.Queue()
    for item in work:
        queue.put_nowait(item)

    limits = httpx.Limits(
        max_connections=concurrency + 8,
        max_keepalive_connections=concurrency + 8,
    )
    timeout = httpx.Timeout(connect=30.0, read=900.0, write=120.0, pool=None)

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(PROGRESS_POLL_SECONDS)
            progress.maybe_emit()

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:

        async def worker() -> None:
            while True:
                try:
                    task_index, row_index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                run = runs[task_index]
                prefix = f"task '{run.name}': " if multi else ""
                handler = select_row_handler(run.config)
                try:
                    if cost.out_of_budget():
                        # Budget spent: do not start any further row.
                        return
                    run.results[row_index] = await handler(
                        client,
                        run.config,
                        run.rows[row_index],
                        row_index,
                        run.prepared[row_index],
                        contexts[task_index],
                        prefix,
                    )
                except BudgetExceeded:
                    return
                finally:
                    queue.task_done()
                    if progress is not None and run.results[row_index] is not None:
                        progress.record_row(run.results[row_index])

        # Ramp workers up one at a time. Each worker takes the next item from the
        # queue, so rows are dispatched in input order; the small stagger keeps
        # simultaneous connection setup from reordering the first requests on
        # the wire. The whole ramp is bounded by RAMP_BUDGET_SECONDS.
        stagger = min(MAX_STAGGER_SECONDS, RAMP_BUDGET_SECONDS / concurrency)
        workers = []
        ticker = asyncio.create_task(heartbeat()) if progress is not None else None
        for slot in range(concurrency):
            workers.append(asyncio.create_task(worker()))
            if slot + 1 < concurrency and not queue.empty():
                await asyncio.sleep(stagger)

        try:
            await asyncio.gather(*workers)
        finally:
            if ticker is not None:
                ticker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ticker

    # Rows are written in input order, so keep only the completed prefix: a
    # budget stop drops the tail rather than leaving a hole in the output.
    for run in runs:
        complete: list[dict] = []
        for result in run.results:
            if result is None:
                break
            complete.append(result)
        run.results = complete
    return global_stats


# --------------------------------------------------------------------------
# Summary and output
# --------------------------------------------------------------------------


def _count_results(results: list[dict]) -> tuple[int, int]:
    """Row-level pass/fail counts; a multi-solution row passes with >=1 solution."""
    passed = 0
    failed = 0
    for result in results:
        row_passed = result["result"]["passed"]
        if isinstance(result["output"], list):
            if row_passed:
                passed += 1
            else:
                failed += 1
            continue
        has_output = result["output"] is not None
        if row_passed is True or (row_passed is None and has_output):
            passed += 1
        if row_passed is False or not has_output:
            failed += 1
    return passed, failed


def _count_solutions(results: list[dict]) -> int:
    total = 0
    for result in results:
        output = result["output"]
        if isinstance(output, list):
            total += len(output)
        elif output is not None:
            total += 1
    return total


def _solution_fields(results: list[dict]) -> dict[str, Any]:
    total_solutions = _count_solutions(results)
    average = total_solutions / len(results) if results else 0.0
    return {
        "total_solutions": total_solutions,
        "avg_solutions_per_input": round(average, 2),
    }


def build_summary(
    runs: list[TaskRun],
    stats: Stats,
    multi: bool = False,
    *,
    cost: CostTracker | None = None,
    resumed: bool = False,
) -> dict:
    total = 0
    passed = 0
    failed = 0
    for run in runs:
        run_passed, run_failed = _count_results(run.results)
        total += len(run.results)
        passed += run_passed
        failed += run_failed

    if stats.first_request_at is not None and stats.last_response_at is not None:
        elapsed = max(0.0, stats.last_response_at - stats.first_request_at)
    else:
        elapsed = 0.0
    throughput = (stats.total_api_calls / elapsed * 60.0) if elapsed > 0 else 0.0

    summary: dict[str, Any] = {
        "total": total,
    }
    if resumed:
        summary["resumed_from"] = sum(run.resumed_from for run in runs)
    summary.update({
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.total_api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    })

    if cost is not None and cost.enabled:
        summary["cost"] = cost.summary()

    # Solution counts only appear once a task can produce more than one solution
    # per input; single-solution runs keep the earlier summary shape exactly.
    if any(not run.config.legacy for run in runs):
        summary.update(_solution_fields([r for run in runs for r in run.results]))

    if multi:
        tasks: dict[str, Any] = {}
        for run in runs:
            run_passed, run_failed = _count_results(run.results)
            entry = {
                "total": len(run.results),
                "passed": run_passed,
                "failed": run_failed,
            }
            if not run.config.legacy:
                entry.update(_solution_fields(run.results))
            entry["total_api_calls"] = run.stats.total_api_calls
            if resumed:
                entry["resumed_from"] = run.resumed_from
            tasks[run.name] = entry
        summary["tasks"] = tasks

    return summary


def write_results(path: str, results: list[dict], kept: list[str] | None = None) -> None:
    """Write one JSONL line per result, after any rows kept by `--resume`."""
    try:
        with open(path, "w", encoding="utf-8") as handle:
            for line in kept or []:
                handle.write(line + "\n")
            for result in results:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ConfigError(f"could not write output file {path}: {exc}") from None


# --------------------------------------------------------------------------
# Resume
# --------------------------------------------------------------------------


def _solution_count(row: Any) -> int:
    output = row.get("output") if isinstance(row, dict) else None
    if isinstance(output, list):
        return len([item for item in output if item is not None])
    return 0 if output is None else 1


def row_is_complete(row: Any, config: TaskConfig) -> bool:
    """True when a previously written output row does not need reprocessing."""
    if not isinstance(row, dict) or "input" not in row or "result" not in row:
        return False
    if config.scheme != "rejection" and config.num_solutions <= 1:
        return True
    # Rejection / multi-solution rows are only complete once they hold as many
    # solutions as the task could ever produce for one input.
    wanted = config.num_solutions
    if not config.legacy:
        wanted = min(wanted, config.attempt_budget)
    return _solution_count(row) >= max(1, wanted)


def resume_state(path: str, config: TaskConfig) -> tuple[int, list[str]]:
    """How many leading input rows are already done, plus the lines to keep."""
    if not os.path.exists(path):
        return 0, []
    if os.path.isdir(path):
        raise ConfigError(f"output path is a directory: {path}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError as exc:
        raise ConfigError(f"could not read output file {path}: {exc}") from None

    kept: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            break  # a truncated final line: reprocess from here
        if not row_is_complete(row, config):
            break
        kept.append(line)
    return len(kept), kept


# --------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------


def estimate_run(runs: list[TaskRun]) -> dict:
    """`--dry-run`: per-task token/cost estimates and a wall-clock guess."""
    tasks: dict[str, Any] = {}
    total_inputs = 0
    total_tokens = 0
    total_cost = 0.0
    total_minutes = 0.0

    for run in runs:
        config = run.config
        inputs = len(run.rows)
        words = [
            sum(count_words(_message_content(message)) for message in messages)
            for messages in run.prepared
        ]
        average_words = (sum(words) / len(words)) if words else 0.0
        prompt_tokens = int(round(inputs * average_words * DRY_RUN_TOKEN_FACTOR))
        completion_tokens = inputs * config.max_tokens
        attempts = config.max_attempts if config.legacy else config.attempt_budget

        if config.cost is not None:
            prompt_cost, completion_cost = config.cost.call_cost(
                prompt_tokens, completion_tokens
            )
            cost = prompt_cost + completion_cost
        else:
            cost = 0.0

        tasks[config.name] = {
            "inputs": inputs,
            "est_prompt_tokens": prompt_tokens,
            "est_completion_tokens": completion_tokens,
            "est_total_tokens": prompt_tokens + completion_tokens,
            "est_cost": round(cost, COST_DECIMALS),
        }
        total_inputs += inputs
        total_tokens += prompt_tokens + completion_tokens
        total_cost += cost
        total_minutes += inputs * attempts / config.effective_rpm

    return {
        "tasks": tasks,
        "total_inputs": total_inputs,
        "est_total_tokens": total_tokens,
        "est_total_cost": round(total_cost, COST_DECIMALS),
        "est_time_minutes": round(total_minutes, COST_DECIMALS),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that exits with code 1 (not 2) on usage errors."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="rejector.py",
        description="Run YAML-configured prompting tasks against an "
        "OpenAI-compatible chat completions API.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run tasks over JSONL input files")
    run_parser.add_argument("--config", required=True, help="path to the YAML config")
    run_parser.add_argument(
        "--input",
        action="append",
        default=None,
        help="JSONL input path, or <task>=<path> for multi-task configs (repeatable)",
    )
    run_parser.add_argument(
        "--input-dir",
        dest="input_dir",
        default=None,
        help="directory holding <task_name>.jsonl input files",
    )
    run_parser.add_argument(
        "--output",
        required=True,
        help="output JSONL path (single task) or output directory (multi-task)",
    )
    run_parser.add_argument(
        "--task",
        action="append",
        dest="task",
        default=None,
        help="run only the named task (repeatable)",
    )
    run_parser.add_argument(
        "--eval-model",
        dest="eval_model",
        default=None,
        help="override the judge model for all selected llm_judge tasks",
    )
    run_parser.add_argument("--api-url", dest="api_url", default=None)
    run_parser.add_argument("--model", default=None)
    run_parser.add_argument("--rpm", default=None)
    run_parser.add_argument("--tpm", default=None, help="tokens per minute budget")
    run_parser.add_argument(
        "--max-concurrent",
        dest="max_concurrent",
        default=None,
        help="hard cap on in-flight requests per task",
    )
    run_parser.add_argument(
        "--budget", default=None, help="stop sending requests once this cost is reached"
    )
    run_parser.add_argument("--max-tokens", dest="max_tokens", default=None)
    run_parser.add_argument("--scheme", choices=list(SCHEMES), default=None)
    run_parser.add_argument("--temperature", default=None)
    run_parser.add_argument("--n", default=None)
    run_parser.add_argument(
        "--num-solutions",
        dest="num_solutions",
        default=None,
        help="number of solutions to collect per input",
    )
    run_parser.add_argument(
        "--api-type",
        dest="api_type",
        choices=list(API_TYPES),
        default=None,
        help="send chat completions or plain completions requests",
    )
    run_parser.add_argument(
        "--chat-template",
        dest="chat_template",
        choices=list(CHAT_TEMPLATES),
        default=None,
        help="template used to render the conversation for completions mode",
    )
    run_parser.add_argument(
        "--icl-strategy",
        dest="icl_strategy",
        choices=list(ICL_STRATEGIES),
        default=None,
        help="override how an ICL setup is chosen for each attempt",
    )
    run_parser.add_argument(
        "--icl-k",
        dest="icl_k",
        default=None,
        help="override how many examples of a setup are used",
    )
    run_parser.add_argument(
        "--resume",
        action="store_true",
        help="skip input rows already present in the output file(s)",
    )
    run_parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="validate config and inputs, print an estimate, make no API calls",
    )
    run_parser.add_argument(
        "--progress",
        action="store_true",
        help="print progress updates to stderr while running",
    )
    return parser


def collect_overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.api_url is not None:
        overrides["api_url"] = args.api_url
    if args.model is not None:
        overrides["model"] = args.model
    if args.scheme is not None:
        overrides["scheme"] = args.scheme
    if args.rpm is not None:
        overrides["rpm"] = _cli_int(args.rpm, "--rpm")
    if args.max_tokens is not None:
        overrides["max_tokens"] = _cli_int(args.max_tokens, "--max-tokens")
    if args.n is not None:
        overrides["n"] = _cli_int(args.n, "--n")
    if args.temperature is not None:
        overrides["temperature"] = _cli_float(args.temperature, "--temperature")
    if args.eval_model is not None:
        overrides["eval_model"] = _cli_text(args.eval_model, "--eval-model")
    if args.num_solutions is not None:
        overrides["num_solutions"] = _cli_int(args.num_solutions, "--num-solutions")
    if args.api_type is not None:
        overrides["api_type"] = args.api_type
    if args.chat_template is not None:
        overrides["chat_template"] = args.chat_template
    if args.icl_strategy is not None:
        overrides["icl_strategy"] = args.icl_strategy
    if args.icl_k is not None:
        overrides["icl_k"] = _cli_int(args.icl_k, "--icl-k")
    if getattr(args, "tpm", None) is not None:
        overrides["tpm"] = _cli_int(args.tpm, "--tpm")
    if getattr(args, "max_concurrent", None) is not None:
        overrides["max_concurrent"] = _cli_int(args.max_concurrent, "--max-concurrent")
    if getattr(args, "budget", None) is not None:
        overrides["budget"] = _cli_float(args.budget, "--budget")
    return overrides


def _cli_int(value: str, flag: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"{flag} must be an integer, got {value!r}") from None


def _cli_float(value: str, flag: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"{flag} must be a number, got {value!r}") from None


def _cli_text(value: str, flag: str) -> str:
    text = str(value).strip()
    if not text:
        raise ConfigError(f"{flag} must be a non-empty string")
    return text


def resolve_inputs(args: argparse.Namespace, bundle: ConfigBundle) -> dict[str, str]:
    """Map each selected task name to its JSONL input path."""
    entries = list(args.input or [])
    names = [task.name for task in bundle.tasks]

    if args.input_dir is not None and entries:
        raise ConfigError(
            "--input and --input-dir are alternative modes; do not combine them"
        )

    if args.input_dir is not None:
        directory = args.input_dir
        if not os.path.isdir(directory):
            raise ConfigError(f"input directory not found: {directory}")
        mapping: dict[str, str] = {}
        for name in names:
            path = os.path.join(directory, f"{name}.jsonl")
            if not os.path.isfile(path):
                raise ConfigError(
                    f"no input file for task '{name}': expected {path}"
                )
            mapping[name] = path
        return mapping

    if not entries:
        raise ConfigError("one of --input or --input-dir is required")

    if not bundle.multi:
        if len(entries) > 1:
            raise ConfigError(
                "--input may only be given once for single-task configs"
            )
        entry = entries[0]
        name, sep, path = entry.partition("=")
        single = names[0] if names else None
        if sep and single is not None and name.strip() == single:
            if not path.strip():
                raise ConfigError(f"--input for task '{single}' has an empty path")
            return {single: path}
        return {single: entry} if single is not None else {}

    mapping = {}
    for entry in entries:
        name, sep, path = entry.partition("=")
        if not sep:
            raise ConfigError(
                "for multi-task configs --input must be given as <task>=<path>, "
                f"got {entry!r}"
            )
        name = name.strip()
        if name not in bundle.all_names:
            available = ", ".join(bundle.all_names)
            raise ConfigError(
                f"--input refers to unknown task {name!r} (available: {available})"
            )
        if name not in names:
            continue  # not selected: ignored for validation and execution
        if not path.strip():
            raise ConfigError(f"--input for task '{name}' has an empty path")
        if name in mapping:
            raise ConfigError(f"--input given more than once for task '{name}'")
        mapping[name] = path

    missing = [name for name in names if name not in mapping]
    if missing:
        raise ConfigError(
            "missing --input for task(s): " + ", ".join(missing)
        )
    return mapping


def resolve_outputs(args: argparse.Namespace, bundle: ConfigBundle) -> dict[str, str]:
    names = [task.name for task in bundle.tasks]
    if not bundle.multi:
        return {name: args.output for name in names}

    directory = args.output
    if os.path.exists(directory) and not os.path.isdir(directory):
        raise ConfigError(
            f"--output must be a directory for multi-task configs: {directory}"
        )
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"could not create output directory {directory}: {exc}") from None
    return {name: os.path.join(directory, f"{name}.jsonl") for name in names}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        overrides = collect_overrides(args)
        bundle = load_config(args.config, overrides, args.task)
        inputs = resolve_inputs(args, bundle)
        outputs = resolve_outputs(args, bundle)

        runs: list[TaskRun] = []
        for task in bundle.tasks:
            run = TaskRun(
                config=task,
                input_path=inputs[task.name],
                output_path=outputs[task.name],
            )
            run.rows = load_rows(run.input_path)
            run.all_rows = run.rows
            run.prepared = prepare_rows(task, run.rows, bundle.multi)
            runs.append(run)

        if args.dry_run:
            print(json.dumps(estimate_run(runs)))
            return EXIT_OK

        if args.resume:
            for run in runs:
                skip, kept = resume_state(run.output_path, run.config)
                skip = min(skip, len(run.rows))
                run.resumed_from = skip
                run.kept = kept[:skip]
                run.rows = run.rows[skip:]
                run.prepared = run.prepared[skip:]
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    cost = CostTracker(
        enabled=cost_configured(runs),
        budget=resolve_budget(runs),
    )

    try:
        stats = asyncio.run(
            run_all(runs, bundle.multi, cost=cost, show_progress=bool(args.progress))
        )
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return EXIT_ERROR

    try:
        for run in runs:
            write_results(run.output_path, run.results, run.kept)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(
        json.dumps(
            build_summary(
                runs, stats, bundle.multi, cost=cost, resumed=bool(args.resume)
            )
        )
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
