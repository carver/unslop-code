"""Loading and validation of the YAML task configuration."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import yaml

from errors import RejectorError
from evaluation import ANSWER_FIELD_TYPES, CHECKS, EXTRACTORS, EvaluationConfig

SCHEMES = frozenset({"greedy", "sample", "rejection"})

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_EXTRACT = "full"


@dataclass(frozen=True)
class PromptConfig:
    """Prompt templates; `{field}` placeholders are filled from each input row."""

    system: str
    user: str


@dataclass(frozen=True)
class GenerationConfig:
    """Sampling parameters and the scheme that drives how many attempts a row gets."""

    scheme: str
    temperature: float
    max_tokens: int
    n: int

    @property
    def attempts(self) -> int:
        """Logical generation attempts per row: `n` for rejection sampling, else 1."""
        return self.n if self.scheme == "rejection" else 1


@dataclass(frozen=True)
class TaskConfig:
    """A fully validated task definition."""

    name: str
    api_url: str
    model: str
    rpm: int
    prompt: PromptConfig
    generation: GenerationConfig
    evaluation: EvaluationConfig | None
    output_field: str


def load_task_config(path: str, overrides: dict[str, Any]) -> TaskConfig:
    """Read the YAML config at `path`, apply CLI overrides, and validate the result."""
    document = _read_yaml(path)
    section = document.get("task")
    if not isinstance(section, dict):
        raise RejectorError(f"{path}: config must contain a 'task' mapping")

    task = _merged(section, overrides, ("api_url", "model", "rpm"))
    rpm = _number(task, "rpm", DEFAULT_RPM, int)
    if rpm < 1:
        raise RejectorError(f"task.rpm must be >= 1, got {rpm}")

    generation = _build_generation(
        _merged(section.get("generation"), overrides, ("scheme", "temperature", "max_tokens", "n"))
    )
    return TaskConfig(
        name=str(task.get("name", "task")),
        api_url=_text(task, "api_url").rstrip("/"),
        model=_text(task, "model"),
        rpm=rpm,
        prompt=_build_prompt(section.get("prompt")),
        generation=generation,
        evaluation=_build_evaluation(section.get("evaluation"), generation.scheme),
        output_field=_text(task, "output_field"),
    )


def _read_yaml(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise RejectorError(f"{path}: expected a YAML mapping at the top level")
    return document


def _merged(section: Any, overrides: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Config section with the CLI overrides that apply to it layered on top."""
    values = dict(section or {})
    values.update({key: overrides[key] for key in keys if overrides.get(key) is not None})
    return values


def _text(task: dict[str, Any], key: str) -> str:
    value = task.get(key)
    if not value:
        raise RejectorError(f"task.{key} is required")
    return str(value)


def _number(values: dict[str, Any], key: str, default: Any, cast: Callable[[Any], Any]) -> Any:
    value = values.get(key, default)
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise RejectorError(f"{key} must be a number, got {value!r}") from None


def _build_prompt(section: Any) -> PromptConfig:
    if not isinstance(section, dict) or not section.get("user"):
        raise RejectorError("task.prompt.user is required")
    return PromptConfig(system=str(section.get("system", "")), user=str(section["user"]))


def _build_generation(values: dict[str, Any]) -> GenerationConfig:
    scheme = str(values.get("scheme", "greedy"))
    if scheme not in SCHEMES:
        raise RejectorError(f"generation.scheme must be one of {sorted(SCHEMES)}, got {scheme!r}")

    temperature = _number(values, "temperature", 0.0, float)
    if scheme == "greedy":
        temperature = 0.0
    elif temperature <= 0:
        raise RejectorError(f"generation.temperature must be > 0 for scheme '{scheme}', got {temperature}")

    n = _number(values, "n", 1, int)
    if n < 1:
        raise RejectorError(f"generation.n must be >= 1, got {n}")

    return GenerationConfig(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_number(values, "max_tokens", DEFAULT_MAX_TOKENS, int),
        n=n,
    )


def _build_evaluation(section: Any, scheme: str) -> EvaluationConfig | None:
    if section is None:
        if scheme == "rejection":
            raise RejectorError("task.evaluation is required for scheme 'rejection'")
        return None
    if not isinstance(section, dict):
        raise RejectorError("task.evaluation must be a mapping")

    eval_type = section.get("type")
    if eval_type not in CHECKS:
        raise RejectorError(f"evaluation.type must be one of {sorted(CHECKS)}, got {eval_type!r}")

    extract = str(section.get("extract", DEFAULT_EXTRACT))
    if extract not in EXTRACTORS:
        raise RejectorError(f"evaluation.extract must be one of {sorted(EXTRACTORS)}, got {extract!r}")

    answer_field = section.get("answer_field")
    if eval_type in ANSWER_FIELD_TYPES and not answer_field:
        raise RejectorError(f"evaluation.answer_field is required for type '{eval_type}'")

    return EvaluationConfig(
        type=eval_type,
        extract=extract,
        answer_field=str(answer_field) if answer_field else None,
        pattern=_compile_pattern(section.get("pattern")) if eval_type == "regex" else None,
    )


def _compile_pattern(pattern: Any) -> re.Pattern[str]:
    if not pattern:
        raise RejectorError("evaluation.pattern is required for type 'regex'")
    try:
        return re.compile(str(pattern))
    except re.error as exc:
        raise RejectorError(f"evaluation.pattern is not a valid regex: {exc}") from None
