"""Loading and validating the YAML configuration.

A config holds either one task (the Part 1 `task` key) or a `tasks` mapping
layered over shared `defaults`. Either shape is normalised into frozen
dataclasses so the rest of the tool never has to reach into raw dictionaries
or re-apply defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")

# Keys each evaluation type cannot work without.
REQUIRED_EVALUATION_KEYS = {
    "exact_match": ("answer_field",),
    "contains": ("answer_field",),
    "regex": ("pattern",),
    "script": ("command_template",),
    "llm_judge": ("judge_prompt", "threshold"),
}

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_SUCCESS_EXIT_CODE = 0
SCRIPT_TIMEOUT_SECONDS = 10.0

# Internal key for a single-task config whose `task.name` is omitted.
UNNAMED_TASK = "task"


class ConfigError(Exception):
    """Raised for any invalid configuration or input; the CLI exits 1 on it."""


@dataclass(frozen=True)
class PromptConfig:
    user: str
    system: str | None


@dataclass(frozen=True)
class GenerationConfig:
    scheme: str
    temperature: float
    max_tokens: int
    n: int


@dataclass(frozen=True)
class ScriptConfig:
    """Extra settings for `type: script` evaluation."""

    command_template: str
    success_exit_code: int
    timeout: float = SCRIPT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class JudgeConfig:
    """Extra settings for `type: llm_judge` evaluation."""

    prompt: PromptConfig
    threshold: float
    model: str | None


@dataclass(frozen=True)
class EvaluationConfig:
    type: str
    extract: str
    answer_field: str | None
    pattern: str | None
    script: ScriptConfig | None
    judge: JudgeConfig | None


@dataclass(frozen=True)
class TaskConfig:
    name: str | None
    api_url: str
    model: str
    rpm: int
    prompt: PromptConfig
    generation: GenerationConfig
    evaluation: EvaluationConfig | None
    output_field: str


@dataclass(frozen=True)
class RunConfig:
    """Every task the config defines, in declaration order."""

    tasks: dict[str, TaskConfig]
    multi: bool


def load_config(path: str | Path, overrides: Mapping[str, Any]) -> RunConfig:
    """Read a YAML config file and apply CLI overrides on top of it."""
    try:
        raw = yaml.safe_load(Path(path).read_text())
    except OSError as error:
        raise ConfigError(f"cannot read config {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"invalid YAML in {path}: {error}") from error
    return build_run_config(raw, overrides)


def build_run_config(raw: Any, overrides: Mapping[str, Any]) -> RunConfig:
    """Validate a parsed config document and merge in the CLI overrides."""
    if not isinstance(raw, Mapping):
        raise ConfigError("config must be a mapping")
    chosen = {key: value for key, value in overrides.items() if value is not None}

    if isinstance(raw.get("task"), Mapping):
        task = _build_task(raw["task"], "task", chosen)
        return RunConfig(tasks={task.name or UNNAMED_TASK: task}, multi=False)

    tasks = raw.get("tasks")
    if not isinstance(tasks, Mapping) or not tasks:
        raise ConfigError("config must have a 'task' section or a non-empty 'tasks' mapping")
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, Mapping):
        raise ConfigError("config 'defaults' must be a mapping")

    built = {}
    for name, body in tasks.items():
        if not isinstance(body, Mapping):
            raise ConfigError(f"tasks.{name} must be a mapping")
        built[str(name)] = _build_task(
            merge(defaults, body), f"tasks.{name}", chosen, name=str(name)
        )
    return RunConfig(tasks=built, multi=True)


def merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Layer `override` onto `base`, merging nested mappings key by key."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = merge(current, value)
        else:
            merged[key] = value
    return merged


def _build_task(
    raw: Mapping[str, Any],
    where: str,
    overrides: Mapping[str, Any],
    name: str | None = None,
) -> TaskConfig:
    """Build one task from an already-merged body; `where` prefixes error labels."""
    generation = _build_generation(raw.get("generation") or {}, overrides, where)
    evaluation = _build_evaluation(raw.get("evaluation"), generation.scheme, overrides, where)
    return TaskConfig(
        name=name or raw.get("name"),
        api_url=_require(overrides.get("api_url") or raw.get("api_url"), f"{where}.api_url"),
        model=_require(overrides.get("model") or raw.get("model"), f"{where}.model"),
        rpm=_positive_int(overrides.get("rpm", raw.get("rpm", DEFAULT_RPM)), f"{where}.rpm"),
        prompt=_build_prompt(raw.get("prompt"), f"{where}.prompt"),
        generation=generation,
        evaluation=evaluation,
        output_field=_require(raw.get("output_field"), f"{where}.output_field"),
    )


def _build_prompt(raw: Any, where: str) -> PromptConfig:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where} must be a mapping with a 'user' template")
    user = _require(raw.get("user"), f"{where}.user")
    return PromptConfig(user=user, system=raw.get("system"))


def _build_generation(
    raw: Mapping[str, Any], overrides: Mapping[str, Any], where: str
) -> GenerationConfig:
    scheme = overrides.get("scheme", raw.get("scheme", "greedy"))
    if scheme not in SCHEMES:
        raise ConfigError(
            f"{where}.generation.scheme must be one of {', '.join(SCHEMES)}, got '{scheme}'"
        )
    label = f"{where}.generation.temperature"
    temperature = _float(overrides.get("temperature", raw.get("temperature", 0.0)), label)
    if scheme == "greedy":
        temperature = 0.0
    elif temperature <= 0:
        raise ConfigError(f"{label} must be > 0 for scheme '{scheme}', got {temperature}")
    return GenerationConfig(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_positive_int(
            overrides.get("max_tokens", raw.get("max_tokens", DEFAULT_MAX_TOKENS)),
            f"{where}.generation.max_tokens",
        ),
        n=_positive_int(overrides.get("n", raw.get("n", 1)), f"{where}.generation.n"),
    )


def _build_evaluation(
    raw: Any, scheme: str, overrides: Mapping[str, Any], where: str
) -> EvaluationConfig | None:
    if raw is None:
        if scheme == "rejection":
            raise ConfigError(f"{where}.evaluation is required for scheme 'rejection'")
        return None
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where}.evaluation must be a mapping")

    eval_type = raw.get("type")
    if eval_type not in EVALUATION_TYPES:
        raise ConfigError(
            f"{where}.evaluation.type must be one of {', '.join(EVALUATION_TYPES)}, "
            f"got '{eval_type}'"
        )
    for key in REQUIRED_EVALUATION_KEYS[eval_type]:
        _require(raw.get(key), f"{where}.evaluation.{key} (required for type '{eval_type}')")

    extract = raw.get("extract", "full")
    if extract not in EXTRACT_METHODS:
        raise ConfigError(
            f"{where}.evaluation.extract must be one of {', '.join(EXTRACT_METHODS)}, "
            f"got '{extract}'"
        )
    return EvaluationConfig(
        type=eval_type,
        extract=extract,
        answer_field=raw.get("answer_field"),
        pattern=raw.get("pattern"),
        script=_build_script(raw, where) if eval_type == "script" else None,
        judge=_build_judge(raw, overrides, where) if eval_type == "llm_judge" else None,
    )


def _build_script(raw: Mapping[str, Any], where: str) -> ScriptConfig:
    return ScriptConfig(
        command_template=raw["command_template"],
        success_exit_code=_int(
            raw.get("success_exit_code", DEFAULT_SUCCESS_EXIT_CODE),
            f"{where}.evaluation.success_exit_code",
        ),
    )


def _build_judge(
    raw: Mapping[str, Any], overrides: Mapping[str, Any], where: str
) -> JudgeConfig:
    """The judge inherits the task's model unless the evaluation names its own."""
    return JudgeConfig(
        prompt=_build_prompt(raw.get("judge_prompt"), f"{where}.evaluation.judge_prompt"),
        threshold=_float(raw.get("threshold"), f"{where}.evaluation.threshold"),
        model=overrides.get("eval_model") or raw.get("model"),
    )


def _require(value: Any, label: str) -> Any:
    if value is None or value == "":
        raise ConfigError(f"{label} is required")
    return value


def _float(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{label} must be a number, got {value!r}") from None


def _int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{label} must be an integer, got {value!r}") from None


def _positive_int(value: Any, label: str) -> int:
    number = _int(value, label)
    if number < 1:
        raise ConfigError(f"{label} must be >= 1, got {number}")
    return number
