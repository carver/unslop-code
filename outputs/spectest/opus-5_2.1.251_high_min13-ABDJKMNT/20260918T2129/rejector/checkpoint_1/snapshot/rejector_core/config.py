"""Task configuration: YAML loading, CLI overrides, and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import ConfigError

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512


@dataclass(frozen=True)
class Prompt:
    """Message templates with `{field}` placeholders."""

    user: str
    system: str | None = None


@dataclass(frozen=True)
class Generation:
    """Decoding parameters for one scheme."""

    scheme: str
    temperature: float
    max_tokens: int
    n: int

    @property
    def max_attempts(self) -> int:
        """Logical generation attempts per row; `n` only applies to rejection."""
        return self.n if self.scheme == "rejection" else 1


@dataclass(frozen=True)
class Evaluation:
    """How a response is judged, and which part of it is compared."""

    type: str
    extract: str
    answer_field: str | None = None
    pattern: str | None = None


@dataclass(frozen=True)
class TaskConfig:
    """A fully validated task."""

    name: str | None
    api_url: str
    model: str
    rpm: int
    prompt: Prompt
    generation: Generation
    output_field: str
    evaluation: Evaluation | None

    @property
    def completions_url(self) -> str:
        return f"{self.api_url.rstrip('/')}/v1/chat/completions"


def load_config(path: str | Path, overrides: dict) -> TaskConfig:
    """Read a YAML config, apply CLI overrides, and validate the result."""
    raw = _read_yaml(Path(path))
    if not isinstance(raw, dict) or not isinstance(raw.get("task"), dict):
        raise ConfigError("config must contain a 'task' mapping")

    task = dict(raw["task"])
    generation = dict(_section(task, "generation"))
    for key in ("api_url", "model", "rpm"):
        if overrides.get(key) is not None:
            task[key] = overrides[key]
    for key in ("scheme", "temperature", "max_tokens", "n"):
        if overrides.get(key) is not None:
            generation[key] = overrides[key]
    task["generation"] = generation

    return _build_task(task)


def _read_yaml(path: Path):
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {exc}") from exc


def _build_task(task: dict) -> TaskConfig:
    for key in ("api_url", "model", "prompt", "output_field"):
        if not task.get(key):
            raise ConfigError(f"task.{key} is required")

    generation = _build_generation(task["generation"])
    evaluation = _build_evaluation(task.get("evaluation"))
    if generation.scheme == "rejection" and evaluation is None:
        raise ConfigError("task.evaluation is required for the rejection scheme")

    return TaskConfig(
        name=task.get("name"),
        api_url=_require_str(task["api_url"], "task.api_url"),
        model=_require_str(task["model"], "task.model"),
        rpm=_require_positive_int(task.get("rpm", DEFAULT_RPM), "task.rpm"),
        prompt=_build_prompt(task["prompt"]),
        generation=generation,
        output_field=_require_str(task["output_field"], "task.output_field"),
        evaluation=evaluation,
    )


def _build_prompt(prompt: dict) -> Prompt:
    if not isinstance(prompt, dict) or not prompt.get("user"):
        raise ConfigError("task.prompt.user is required")
    system = prompt.get("system")
    return Prompt(
        user=_require_str(prompt["user"], "task.prompt.user"),
        system=None if system is None else _require_str(system, "task.prompt.system"),
    )


def _build_generation(generation: dict) -> Generation:
    scheme = generation.get("scheme", "greedy")
    if scheme not in SCHEMES:
        raise ConfigError(f"unknown generation scheme '{scheme}'; expected one of {', '.join(SCHEMES)}")

    temperature = _require_float(generation.get("temperature", 0.0), "task.generation.temperature")
    if scheme == "greedy":
        temperature = 0.0
    elif temperature <= 0:
        raise ConfigError(f"task.generation.temperature must be > 0 for the {scheme} scheme")

    return Generation(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_require_positive_int(
            generation.get("max_tokens", DEFAULT_MAX_TOKENS), "task.generation.max_tokens"
        ),
        n=_require_positive_int(generation.get("n", 1), "task.generation.n"),
    )


def _build_evaluation(evaluation) -> Evaluation | None:
    if evaluation is None:
        return None
    if not isinstance(evaluation, dict):
        raise ConfigError("task.evaluation must be a mapping")

    eval_type = evaluation.get("type")
    if eval_type not in EVALUATION_TYPES:
        raise ConfigError(
            f"unknown evaluation type '{eval_type}'; expected one of {', '.join(EVALUATION_TYPES)}"
        )

    extract = evaluation.get("extract", "full")
    if extract not in EXTRACT_METHODS:
        raise ConfigError(
            f"unknown extract method '{extract}'; expected one of {', '.join(EXTRACT_METHODS)}"
        )

    answer_field = evaluation.get("answer_field")
    if eval_type in ("exact_match", "contains") and not answer_field:
        raise ConfigError(f"task.evaluation.answer_field is required for the {eval_type} type")

    pattern = evaluation.get("pattern")
    if eval_type == "regex" and not pattern:
        raise ConfigError("task.evaluation.pattern is required for the regex type")

    return Evaluation(type=eval_type, extract=extract, answer_field=answer_field, pattern=pattern)


def _section(task: dict, key: str) -> dict:
    value = task.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"task.{key} must be a mapping")
    return value


def _require_str(value, label: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be a string")
    return value


def _require_positive_int(value, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{label} must be a positive integer")
    return value


def _require_float(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} must be a number")
    return float(value)
