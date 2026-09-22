"""Loading and validating the YAML task configuration.

The config is normalised into frozen dataclasses so the rest of the tool never
has to reach into raw dictionaries or re-apply defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")

# Keys each evaluation type cannot work without.
REQUIRED_EVALUATION_KEYS = {
    "exact_match": ("answer_field",),
    "contains": ("answer_field",),
    "regex": ("pattern",),
}

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512


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
class EvaluationConfig:
    type: str
    extract: str
    answer_field: str | None
    pattern: str | None


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


def load_config(path: str | Path, overrides: Mapping[str, Any]) -> TaskConfig:
    """Read a YAML config file and apply CLI overrides on top of it."""
    try:
        raw = yaml.safe_load(Path(path).read_text())
    except OSError as error:
        raise ConfigError(f"cannot read config {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"invalid YAML in {path}: {error}") from error
    return build_task_config(raw, overrides)


def build_task_config(raw: Any, overrides: Mapping[str, Any]) -> TaskConfig:
    """Validate a parsed config document and merge in the CLI overrides."""
    if not isinstance(raw, Mapping) or not isinstance(raw.get("task"), Mapping):
        raise ConfigError("config must be a mapping with a 'task' section")
    task = dict(raw["task"])
    chosen = {key: value for key, value in overrides.items() if value is not None}

    generation = _build_generation(task.get("generation") or {}, chosen)
    evaluation = _build_evaluation(task.get("evaluation"), generation.scheme)
    return TaskConfig(
        name=task.get("name"),
        api_url=_require(chosen.get("api_url") or task.get("api_url"), "task.api_url"),
        model=_require(chosen.get("model") or task.get("model"), "task.model"),
        rpm=_positive_int(chosen.get("rpm", task.get("rpm", DEFAULT_RPM)), "task.rpm"),
        prompt=_build_prompt(task.get("prompt")),
        generation=generation,
        evaluation=evaluation,
        output_field=_require(task.get("output_field"), "task.output_field"),
    )


def _build_prompt(raw: Any) -> PromptConfig:
    if not isinstance(raw, Mapping):
        raise ConfigError("task.prompt must be a mapping with a 'user' template")
    system = raw.get("system")
    return PromptConfig(user=_require(raw.get("user"), "task.prompt.user"), system=system)


def _build_generation(raw: Mapping[str, Any], overrides: Mapping[str, Any]) -> GenerationConfig:
    scheme = overrides.get("scheme", raw.get("scheme", "greedy"))
    if scheme not in SCHEMES:
        raise ConfigError(
            f"task.generation.scheme must be one of {', '.join(SCHEMES)}, got '{scheme}'"
        )
    temperature = _float(
        overrides.get("temperature", raw.get("temperature", 0.0)),
        "task.generation.temperature",
    )
    if scheme == "greedy":
        temperature = 0.0
    elif temperature <= 0:
        raise ConfigError(
            f"task.generation.temperature must be > 0 for scheme '{scheme}', got {temperature}"
        )
    return GenerationConfig(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_positive_int(
            overrides.get("max_tokens", raw.get("max_tokens", DEFAULT_MAX_TOKENS)),
            "task.generation.max_tokens",
        ),
        n=_positive_int(overrides.get("n", raw.get("n", 1)), "task.generation.n"),
    )


def _build_evaluation(raw: Any, scheme: str) -> EvaluationConfig | None:
    if raw is None:
        if scheme == "rejection":
            raise ConfigError("task.evaluation is required for scheme 'rejection'")
        return None
    if not isinstance(raw, Mapping):
        raise ConfigError("task.evaluation must be a mapping")

    eval_type = raw.get("type")
    if eval_type not in EVALUATION_TYPES:
        raise ConfigError(
            f"task.evaluation.type must be one of {', '.join(EVALUATION_TYPES)}, "
            f"got '{eval_type}'"
        )
    for key in REQUIRED_EVALUATION_KEYS[eval_type]:
        _require(raw.get(key), f"task.evaluation.{key} (required for type '{eval_type}')")

    extract = raw.get("extract", "full")
    if extract not in EXTRACT_METHODS:
        raise ConfigError(
            f"task.evaluation.extract must be one of {', '.join(EXTRACT_METHODS)}, "
            f"got '{extract}'"
        )
    return EvaluationConfig(
        type=eval_type,
        extract=extract,
        answer_field=raw.get("answer_field"),
        pattern=raw.get("pattern"),
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


def _positive_int(value: Any, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{label} must be an integer, got {value!r}") from None
    if number < 1:
        raise ConfigError(f"{label} must be >= 1, got {number}")
    return number
