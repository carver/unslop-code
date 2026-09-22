"""Loading and validating the YAML task configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")
ANSWER_FIELD_TYPES = ("exact_match", "contains")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512


class ConfigError(Exception):
    """A task config that cannot be used; reported on stderr with exit code 1."""


@dataclass(frozen=True)
class EvaluationConfig:
    type: str
    answer_field: str | None = None
    extract: str = "full"
    pattern: str | None = None


@dataclass(frozen=True)
class GenerationConfig:
    scheme: str
    temperature: float
    max_tokens: int
    n: int


@dataclass(frozen=True)
class TaskConfig:
    name: str
    api_url: str
    model: str
    rpm: int
    system_template: str | None
    user_template: str
    output_field: str
    generation: GenerationConfig
    evaluation: EvaluationConfig | None

    @property
    def answer_field(self) -> str | None:
        """The input field the evaluation compares against, if any."""
        return self.evaluation.answer_field if self.evaluation else None


@dataclass
class Overrides:
    """CLI flags that replace the corresponding config values when provided."""

    api_url: str | None = None
    model: str | None = None
    rpm: int | None = None
    max_tokens: int | None = None
    scheme: str | None = None
    temperature: float | None = None
    n: int | None = None

    def applied_to(self, task: dict) -> dict:
        """Return `task` with the provided overrides merged in."""
        merged = dict(task)
        generation = dict(merged.get("generation") or {})
        for key in ("api_url", "model", "rpm"):
            if getattr(self, key) is not None:
                merged[key] = getattr(self, key)
        for key in ("max_tokens", "scheme", "temperature", "n"):
            if getattr(self, key) is not None:
                generation[key] = getattr(self, key)
        merged["generation"] = generation
        return merged


def load_config(path: Path, overrides: Overrides) -> TaskConfig:
    """Read, override, and validate the task config at `path`."""
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("task"), dict):
        raise ConfigError("config must contain a 'task' mapping")

    task = overrides.applied_to(raw["task"])
    generation = _build_generation(task["generation"])
    evaluation = _build_evaluation(task.get("evaluation"), generation.scheme)
    system_template, user_template = _build_prompt(task.get("prompt"))

    return TaskConfig(
        name=str(task.get("name", "task")),
        api_url=_require_text(task, "api_url").rstrip("/"),
        model=_require_text(task, "model"),
        rpm=_positive_int(task.get("rpm", DEFAULT_RPM), "rpm"),
        system_template=system_template,
        user_template=user_template,
        output_field=_require_text(task, "output_field"),
        generation=generation,
        evaluation=evaluation,
    )


def _require_text(task: dict, key: str) -> str:
    value = task.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"task.{key} is required and must be a non-empty string")
    return value


def _positive_int(value, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{name} must be a positive integer, got {value!r}")
    return value


def _build_prompt(prompt) -> tuple[str | None, str]:
    """Pull the system (optional) and user (required) templates out of `prompt`."""
    if not isinstance(prompt, dict) or not isinstance(prompt.get("user"), str):
        raise ConfigError("task.prompt must be a mapping with a 'user' template")
    system = prompt.get("system")
    if system is not None and not isinstance(system, str):
        raise ConfigError("task.prompt.system must be a string")
    return system, prompt["user"]


def _build_generation(raw) -> GenerationConfig:
    """Validate generation settings and resolve the scheme's temperature rule."""
    generation = raw if isinstance(raw, dict) else {}
    scheme = generation.get("scheme", "greedy")
    if scheme not in SCHEMES:
        raise ConfigError(
            f"generation.scheme must be one of {', '.join(SCHEMES)}, got {scheme!r}"
        )

    temperature = _scheme_temperature(scheme, generation.get("temperature"))
    n = _positive_int(generation.get("n", 1), "generation.n")
    max_tokens = _positive_int(
        generation.get("max_tokens", DEFAULT_MAX_TOKENS), "generation.max_tokens"
    )
    return GenerationConfig(
        scheme=scheme, temperature=temperature, max_tokens=max_tokens, n=n
    )


def _scheme_temperature(scheme: str, temperature) -> float:
    """`greedy` forces 0.0; the sampling schemes require a positive value."""
    if scheme == "greedy":
        return 0.0
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
        raise ConfigError(
            f"generation.temperature is required for scheme {scheme!r} and must be > 0"
        )
    if temperature <= 0:
        raise ConfigError(
            f"generation.temperature must be > 0 for scheme {scheme!r}, got {temperature!r}"
        )
    return float(temperature)


def _build_evaluation(raw, scheme: str) -> EvaluationConfig | None:
    """Validate the evaluation block, which only `rejection` requires."""
    if raw is None:
        if scheme == "rejection":
            raise ConfigError("task.evaluation is required for scheme 'rejection'")
        return None
    if not isinstance(raw, dict):
        raise ConfigError("task.evaluation must be a mapping")

    eval_type = raw.get("type")
    if eval_type not in EVALUATION_TYPES:
        raise ConfigError(
            f"evaluation.type must be one of {', '.join(EVALUATION_TYPES)}, "
            f"got {eval_type!r}"
        )

    extract = raw.get("extract", "full")
    if extract not in EXTRACT_METHODS:
        raise ConfigError(
            f"evaluation.extract must be one of {', '.join(EXTRACT_METHODS)}, "
            f"got {extract!r}"
        )

    answer_field = raw.get("answer_field")
    if eval_type in ANSWER_FIELD_TYPES and not isinstance(answer_field, str):
        raise ConfigError(f"evaluation.answer_field is required for type {eval_type!r}")

    pattern = raw.get("pattern")
    if eval_type == "regex":
        pattern = _compiled_pattern(pattern)

    return EvaluationConfig(
        type=eval_type, answer_field=answer_field, extract=extract, pattern=pattern
    )


def _compiled_pattern(pattern) -> str:
    if not isinstance(pattern, str):
        raise ConfigError("evaluation.pattern is required for type 'regex'")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"evaluation.pattern is not a valid regex: {exc}") from exc
    return pattern
