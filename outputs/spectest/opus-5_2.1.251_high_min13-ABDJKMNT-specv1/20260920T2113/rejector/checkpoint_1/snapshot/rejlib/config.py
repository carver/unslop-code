"""Task configuration: YAML loading, CLI overrides, and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from rejlib.errors import ConfigError

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_EXTRACT = "full"


@dataclass(frozen=True)
class Evaluation:
    """How a response is judged against its input row."""

    type: str
    answer_field: str | None = None
    extract: str = DEFAULT_EXTRACT
    pattern: str | None = None


@dataclass(frozen=True)
class Generation:
    """Sampling parameters for one task."""

    scheme: str = "greedy"
    temperature: float = 0.0
    max_tokens: int = DEFAULT_MAX_TOKENS
    n: int = 1


@dataclass(frozen=True)
class TaskConfig:
    """A validated task definition."""

    api_url: str
    model: str
    user_prompt: str
    output_field: str
    generation: Generation
    evaluation: Evaluation | None
    name: str | None = None
    system_prompt: str | None = None
    rpm: int = DEFAULT_RPM

    @property
    def chat_url(self) -> str:
        return f"{self.api_url.rstrip('/')}/v1/chat/completions"


def load_config(path, overrides: dict | None = None) -> TaskConfig:
    """Read the YAML task config at ``path``, apply CLI overrides, and validate.

    Overrides with a value of ``None`` are treated as "not provided".
    """
    provided = {key: value for key, value in (overrides or {}).items() if value is not None}
    task = _read_task(Path(path))
    prompt = _submapping(task, "prompt")

    config = TaskConfig(
        name=task.get("name"),
        api_url=provided.get("api_url") or _required_text(task, "api_url"),
        model=provided.get("model") or _required_text(task, "model"),
        rpm=_positive_int("rpm", provided.get("rpm", task.get("rpm", DEFAULT_RPM))),
        system_prompt=prompt.get("system"),
        user_prompt=_required_text(prompt, "user", label="prompt.user"),
        generation=_generation(_submapping(task, "generation"), provided),
        evaluation=_evaluation(task.get("evaluation")),
        output_field=_required_text(task, "output_field"),
    )
    if config.generation.scheme == "rejection" and config.evaluation is None:
        raise ConfigError("task.evaluation is required for scheme 'rejection'")
    return config


def _read_task(path: Path) -> dict:
    try:
        text = path.read_text()
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in config {path}: {exc}") from exc
    task = document.get("task") if isinstance(document, dict) else None
    if not isinstance(task, dict):
        raise ConfigError(f"config {path} must contain a 'task' mapping")
    return task


def _generation(raw: dict, provided: dict) -> Generation:
    """Merge config and overrides, then enforce the per-scheme temperature rules."""
    scheme = provided.get("scheme", raw.get("scheme", "greedy"))
    if scheme not in SCHEMES:
        raise ConfigError(
            f"task.generation.scheme must be one of {', '.join(SCHEMES)}, got {scheme!r}"
        )
    requested = provided.get("temperature", raw.get("temperature", 0.0))
    generation = Generation(
        scheme=scheme,
        temperature=0.0 if scheme == "greedy" else _temperature(requested),
        max_tokens=_positive_int(
            "max_tokens", provided.get("max_tokens", raw.get("max_tokens", DEFAULT_MAX_TOKENS))
        ),
        n=_positive_int("n", provided.get("n", raw.get("n", 1))),
    )
    if scheme != "greedy" and generation.temperature <= 0.0:
        raise ConfigError(f"task.generation.temperature must be > 0 for scheme {scheme!r}")
    return generation


def _evaluation(raw) -> Evaluation | None:
    """Build the evaluation, or ``None`` when the task configures none."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("task.evaluation must be a mapping")

    eval_type = raw.get("type")
    if eval_type not in EVALUATION_TYPES:
        raise ConfigError(
            f"task.evaluation.type must be one of {', '.join(EVALUATION_TYPES)}, got {eval_type!r}"
        )
    extract = raw.get("extract") or DEFAULT_EXTRACT
    if extract not in EXTRACT_METHODS:
        raise ConfigError(
            f"task.evaluation.extract must be one of {', '.join(EXTRACT_METHODS)}, got {extract!r}"
        )

    evaluation = Evaluation(
        type=eval_type,
        answer_field=raw.get("answer_field"),
        extract=extract,
        pattern=raw.get("pattern"),
    )
    if eval_type == "regex":
        _compiled_pattern(evaluation.pattern)
    elif not evaluation.answer_field:
        raise ConfigError(f"task.evaluation.answer_field is required for type {eval_type!r}")
    return evaluation


def _compiled_pattern(pattern):
    if not isinstance(pattern, str) or not pattern:
        raise ConfigError("task.evaluation.pattern is required for type 'regex'")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"task.evaluation.pattern is not a valid regex: {exc}") from exc


def _submapping(mapping: dict, key: str) -> dict:
    value = mapping.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"task.{key} must be a mapping")
    return value


def _required_text(mapping: dict, key: str, label: str | None = None) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"task.{label or key} is required and must be a non-empty string")
    return value


def _positive_int(key: str, value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"task.{key} must be a positive integer, got {value!r}")
    return value


def _temperature(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ConfigError(f"task.generation.temperature must be a non-negative number, got {value!r}")
    return float(value)
