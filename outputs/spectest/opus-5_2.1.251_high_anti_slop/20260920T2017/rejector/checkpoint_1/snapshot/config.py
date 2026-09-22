"""Loading and validation of the YAML task configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from errors import ConfigError

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")

DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 512
DEFAULT_EXTRACT = "full"

#: CLI overrides, mapped to the config section they replace a value in.
TASK_OVERRIDES = ("api_url", "model", "rpm")
GENERATION_OVERRIDES = ("scheme", "temperature", "max_tokens", "n")


@dataclass(frozen=True)
class PromptConfig:
    """Prompt templates with `{field}` placeholders resolved per input row."""

    system: str
    user: str


@dataclass(frozen=True)
class GenerationConfig:
    """Sampling parameters for one scheme.

    `n` is the number of rejection-sampling attempts; it is normalised to 1 for
    the `greedy` and `sample` schemes, which always make a single attempt.
    """

    scheme: str
    temperature: float
    max_tokens: int
    n: int


@dataclass(frozen=True)
class EvaluationConfig:
    """How a response is judged. `answer_field` names a field of the input row."""

    type: str
    extract: str
    answer_field: str | None
    pattern: str | None


@dataclass(frozen=True)
class TaskConfig:
    name: str
    api_url: str
    model: str
    rpm: int
    prompt: PromptConfig
    generation: GenerationConfig
    evaluation: EvaluationConfig | None
    output_field: str


def load_config(path: str, overrides: dict[str, Any] | None = None) -> TaskConfig:
    """Read the task config, apply CLI overrides, and validate the result.

    Raises:
        ConfigError: the file is unreadable or the configuration is invalid.
    """
    task = _read_task(path)
    for key, value in (overrides or {}).items():
        section = task.setdefault("generation", {}) if key in GENERATION_OVERRIDES else task
        section[key] = value
    return _build_task(task)


def _read_task(path: str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(Path(path).read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"cannot parse config {path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("task"), dict):
        raise ConfigError(f"config {path} must contain a 'task' mapping")
    return document["task"]


def _build_task(task: dict[str, Any]) -> TaskConfig:
    prompt = _require(task, "prompt", dict, "task")
    rpm = _require(task, "rpm", int, "task")
    if rpm <= 0:
        raise ConfigError("task.rpm must be > 0")
    generation = _build_generation(_optional(task, "generation", dict, {}, "task"))
    return TaskConfig(
        name=_require(task, "name", str, "task"),
        api_url=_require(task, "api_url", str, "task"),
        model=_require(task, "model", str, "task"),
        rpm=rpm,
        prompt=PromptConfig(
            system=_require(prompt, "system", str, "task.prompt"),
            user=_require(prompt, "user", str, "task.prompt"),
        ),
        generation=generation,
        evaluation=_build_evaluation(task.get("evaluation"), generation.scheme),
        output_field=_require(task, "output_field", str, "task"),
    )


def _build_generation(generation: dict[str, Any]) -> GenerationConfig:
    where = "task.generation"
    scheme = _optional(generation, "scheme", str, "greedy", where)
    if scheme not in SCHEMES:
        raise ConfigError(f"{where}.scheme must be one of {', '.join(SCHEMES)}")

    temperature = float(_optional(generation, "temperature", (int, float), DEFAULT_TEMPERATURE, where))
    if scheme == "greedy":
        temperature = 0.0
    elif temperature <= 0:
        raise ConfigError(f"{where}.temperature must be > 0 for scheme '{scheme}'")

    n = _optional(generation, "n", int, 1, where)
    if scheme == "rejection" and n < 1:
        raise ConfigError(f"{where}.n must be >= 1 for scheme 'rejection'")

    return GenerationConfig(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_optional(generation, "max_tokens", int, DEFAULT_MAX_TOKENS, where),
        n=n if scheme == "rejection" else 1,
    )


def _build_evaluation(evaluation: Any, scheme: str) -> EvaluationConfig | None:
    where = "task.evaluation"
    if evaluation is None:
        if scheme == "rejection":
            raise ConfigError(f"{where} is required for scheme 'rejection'")
        return None
    if not isinstance(evaluation, dict):
        raise ConfigError(f"{where} must be a mapping")

    kind = _require(evaluation, "type", str, where)
    if kind not in EVALUATION_TYPES:
        raise ConfigError(f"{where}.type must be one of {', '.join(EVALUATION_TYPES)}")
    extract = _optional(evaluation, "extract", str, DEFAULT_EXTRACT, where)
    if extract not in EXTRACT_METHODS:
        raise ConfigError(f"{where}.extract must be one of {', '.join(EXTRACT_METHODS)}")

    pattern = None
    answer_field = None
    if kind == "regex":
        pattern = _require(evaluation, "pattern", str, where)
        _compile_pattern(pattern)
    else:
        answer_field = _require(evaluation, "answer_field", str, where)

    return EvaluationConfig(type=kind, extract=extract, answer_field=answer_field, pattern=pattern)


def _compile_pattern(pattern: str) -> None:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"task.evaluation.pattern is not a valid regex: {exc}") from exc


def _require(mapping: dict[str, Any], key: str, types: type | tuple[type, ...], where: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"{where}.{key} is required")
    return _checked(mapping[key], types, f"{where}.{key}")


def _optional(
    mapping: dict[str, Any], key: str, types: type | tuple[type, ...], default: Any, where: str
) -> Any:
    if mapping.get(key) is None:
        return default
    return _checked(mapping[key], types, f"{where}.{key}")


def _checked(value: Any, types: type | tuple[type, ...], where: str) -> Any:
    if not isinstance(value, types):
        names = types if isinstance(types, tuple) else (types,)
        raise ConfigError(f"{where} must be of type {' or '.join(t.__name__ for t in names)}")
    return value
