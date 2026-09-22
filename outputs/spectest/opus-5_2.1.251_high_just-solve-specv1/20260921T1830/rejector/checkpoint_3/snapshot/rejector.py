#!/usr/bin/env python3
"""rejector.py - batch prompting CLI for OpenAI-compatible chat completion APIs.

Reads a YAML config (one task, or many named tasks sharing `defaults`) plus a
JSONL input file per task, renders prompts for every row, issues chat-completion
requests concurrently (dispatched in input order), optionally evaluates each
response, and writes one JSONL result per input row.

Supported generation schemes: greedy, sample, rejection.
Supported evaluations: exact_match, contains, regex, script, llm_judge.
Optional in-context learning (ICL) setups supply few-shot examples, and a task
may collect several solutions per input (`num_solutions`).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import re
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import yaml

EXIT_OK = 0
EXIT_ERROR = 1

SCHEMES = ("greedy", "sample", "rejection")
ICL_STRATEGIES = ("fixed", "random", "round_robin")
EVAL_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")

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
class IclConfig:
    setups: list[IclSetup]
    k: int | None = None
    strategy: str = DEFAULT_ICL_STRATEGY


@dataclass
class TaskConfig:
    name: str
    api_url: str
    model: str
    rpm: int
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

    @property
    def endpoint(self) -> str:
        return self.api_url.rstrip("/") + "/v1/chat/completions"

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

    rpm_value = overrides.get("rpm")
    if rpm_value is None:
        rpm_value = task.get("rpm", DEFAULT_RPM)
    rpm = _as_int(rpm_value, f"{label}.rpm", minimum=1)

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
    else:  # rejection
        if temperature <= 0:
            raise ConfigError(
                f"scheme 'rejection' requires {label}.generation.temperature > 0, "
                f"got {temperature}"
            )
        if evaluation is None:
            raise ConfigError(f"scheme 'rejection' requires a {label}.evaluation section")

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
    stats: "Stats",
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
        request = ApiRequest(
            endpoint=config.endpoint,
            model=config.judge_model,
            temperature=JUDGE_TEMPERATURE,
            max_tokens=config.max_tokens,
            messages=messages,
        )
        call = await call_api(client, request, stats)
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


@dataclass
class CallResult:
    ok: bool
    content: str | None = None
    meta: dict = field(default_factory=dict)


def _usage_int(usage: Any, key: str) -> int:
    if isinstance(usage, dict):
        value = usage.get(key)
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return int(value)
    return 0


async def call_api(
    client: httpx.AsyncClient, request: ApiRequest, stats: Stats
) -> CallResult:
    """One logical attempt: up to MAX_HTTP_ATTEMPTS HTTP requests on 5xx/transport errors."""
    payload = {
        "model": request.model,
        "messages": request.messages,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }

    last_error = "request failed"
    last_latency = 0

    for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
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
                        content, finish_reason, usage = parsed
                        prompt_tokens = _usage_int(usage, "prompt_tokens")
                        completion_tokens = _usage_int(usage, "completion_tokens")
                        stats.add_tokens(prompt_tokens, completion_tokens)
                        return CallResult(
                            ok=True,
                            content=content,
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


def _parse_completion(body: Any) -> tuple[str, Any, Any] | None:
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
    if content is None:
        return None
    return str(content), choice.get("finish_reason"), body.get("usage")


# --------------------------------------------------------------------------
# Row processing
# --------------------------------------------------------------------------


async def process_row(
    client: httpx.AsyncClient,
    config: TaskConfig,
    row: dict,
    row_index: int,
    messages: list[dict],
    stats: Stats,
    prefix: str = "",
) -> dict:
    evaluation = config.evaluation
    metas: list[dict] = []
    attempts = 0
    output_text: str | None = None
    passed: bool | None = None
    extracted: str | None = None
    judge_score: Any = None

    request = ApiRequest(
        endpoint=config.endpoint,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        messages=messages,
    )

    for _ in range(config.max_attempts):
        attempts += 1
        call = await call_api(client, request, stats)
        meta = dict(call.meta)
        metas.append(meta)

        if not call.ok:
            # Hard failure after retries: the row fails and we stop here.
            output_text = None
            passed = False if evaluation is not None else None
            extracted = None
            judge_score = None
            break

        if evaluation is None:
            output_text = call.content
            passed = None
            extracted = None
            break

        outcome = await evaluate_candidate(
            client, config, row, row_index, call.content or "", stats, prefix
        )
        if outcome.judge_meta is not None:
            meta["judge_meta"] = outcome.judge_meta

        if config.scheme != "rejection":
            output_text = call.content
            passed = outcome.passed
            extracted = outcome.extracted
            judge_score = outcome.judge_score
            break

        if outcome.passed:
            output_text = call.content
            passed = True
            extracted = outcome.extracted
            judge_score = outcome.judge_score
            break

        # Rejected: discard this candidate and try again (if budget remains).
        output_text = None
        passed = False
        extracted = None
        judge_score = None

    meta_out: Any = metas[0] if len(metas) == 1 else metas

    result: dict[str, Any] = {
        "passed": passed,
        "extracted_answer": extracted if output_text is not None else None,
    }
    if evaluation is not None and evaluation.type == "llm_judge":
        result["judge_score"] = judge_score if output_text is not None else None
    result["attempts"] = attempts

    return {
        "input": row,
        "output": None if output_text is None else {config.output_field: output_text},
        "result": result,
        "meta": meta_out,
    }


async def process_row_multi(
    client: httpx.AsyncClient,
    config: TaskConfig,
    row: dict,
    row_index: int,
    messages: list[dict],
    stats: Stats,
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

        request = ApiRequest(
            endpoint=config.endpoint,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            messages=with_icl(messages, setup),
        )
        call = await call_api(client, request, stats)
        meta = dict(call.meta)
        meta["icl_setup"] = setup_name

        if not call.ok:
            # Hard failure after retries: this attempt yields nothing and we stop.
            meta["evaluation_passed"] = False if evaluation is not None else None
            metas.append(meta)
            break

        outcome = None
        if evaluation is not None:
            outcome = await evaluate_candidate(
                client, config, row, row_index, call.content or "", stats, prefix
            )
        passed = outcome.passed if outcome is not None else None
        meta["evaluation_passed"] = passed
        if outcome is not None and outcome.judge_meta is not None:
            meta["judge_meta"] = outcome.judge_meta
        metas.append(meta)

        if passed:
            passed_count += 1
        if config.scheme != "rejection" or passed:
            outputs.append({config.output_field: call.content, "icl_setup": setup_name})

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

    @property
    def name(self) -> str:
        return self.config.name


def compute_concurrency(runs: list[TaskRun], work_count: int) -> int:
    if work_count <= 0:
        return 1
    target = sum(run.config.rpm for run in runs if run.rows)
    target = max(target, MIN_CONCURRENCY)
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


async def run_all(runs: list[TaskRun], multi: bool = False) -> Stats:
    global_stats = Stats()
    for run in runs:
        run.stats.parent = global_stats
        run.results = [None] * len(run.rows)  # type: ignore[list-item]

    work = work_order(runs)
    if not work:
        return global_stats

    concurrency = compute_concurrency(runs, len(work))
    queue: asyncio.Queue[tuple[int, int]] = asyncio.Queue()
    for item in work:
        queue.put_nowait(item)

    limits = httpx.Limits(
        max_connections=concurrency + 8,
        max_keepalive_connections=concurrency + 8,
    )
    timeout = httpx.Timeout(connect=30.0, read=900.0, write=120.0, pool=None)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:

        async def worker() -> None:
            while True:
                try:
                    task_index, row_index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                run = runs[task_index]
                prefix = f"task '{run.name}': " if multi else ""
                handler = process_row if run.config.legacy else process_row_multi
                try:
                    run.results[row_index] = await handler(
                        client,
                        run.config,
                        run.rows[row_index],
                        row_index,
                        run.prepared[row_index],
                        run.stats,
                        prefix,
                    )
                finally:
                    queue.task_done()

        # Ramp workers up one at a time. Each worker takes the next item from the
        # queue, so rows are dispatched in input order; the small stagger keeps
        # simultaneous connection setup from reordering the first requests on
        # the wire. The whole ramp is bounded by RAMP_BUDGET_SECONDS.
        stagger = min(MAX_STAGGER_SECONDS, RAMP_BUDGET_SECONDS / concurrency)
        workers = []
        for slot in range(concurrency):
            workers.append(asyncio.create_task(worker()))
            if slot + 1 < concurrency and not queue.empty():
                await asyncio.sleep(stagger)

        await asyncio.gather(*workers)

    for run in runs:
        run.results = [result for result in run.results if result is not None]
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


def build_summary(runs: list[TaskRun], stats: Stats, multi: bool = False) -> dict:
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
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": stats.prompt_tokens,
        "total_completion_tokens": stats.completion_tokens,
        "total_api_calls": stats.total_api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }

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
            tasks[run.name] = entry
        summary["tasks"] = tasks

    return summary


def write_results(path: str, results: list[dict]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as handle:
            for result in results:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ConfigError(f"could not write output file {path}: {exc}") from None


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
    if args.icl_strategy is not None:
        overrides["icl_strategy"] = args.icl_strategy
    if args.icl_k is not None:
        overrides["icl_k"] = _cli_int(args.icl_k, "--icl-k")
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
            run.prepared = prepare_rows(task, run.rows, bundle.multi)
            runs.append(run)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        stats = asyncio.run(run_all(runs, bundle.multi))
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return EXIT_ERROR

    try:
        for run in runs:
            write_results(run.output_path, run.results)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(json.dumps(build_summary(runs, stats, bundle.multi)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
