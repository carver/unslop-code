"""Task configuration: YAML loading, CLI override merging, and validation."""

import re
from dataclasses import dataclass
from typing import Any, Mapping

import yaml

from errors import ConfigError

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")
ANSWER_FIELD_TYPES = ("exact_match", "contains")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_SCHEME = "greedy"
DEFAULT_EXTRACT = "full"

#: CLI overrides that replace values on the ``task`` mapping.
TASK_OVERRIDES = ("api_url", "model", "rpm")
#: CLI overrides that replace values on the ``task.generation`` mapping.
GENERATION_OVERRIDES = ("scheme", "temperature", "max_tokens", "n")


@dataclass(frozen=True)
class PromptConfig:
    """Prompt templates with ``{field}`` placeholders resolved per input row."""

    user: str
    system: str | None = None


@dataclass(frozen=True)
class GenerationConfig:
    """How responses are produced for each row."""

    scheme: str
    temperature: float
    max_tokens: int
    n: int


@dataclass(frozen=True)
class EvaluationConfig:
    """How a response is judged to pass or fail."""

    type: str
    extract: str
    answer_field: str | None = None
    pattern: str | None = None


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


def load_task_config(path: str, overrides: Mapping[str, Any]) -> TaskConfig:
    """Read the YAML config at ``path``, apply non-``None`` overrides, and validate it."""
    document = _read_yaml(path)
    task = document.get("task") if isinstance(document, dict) else None
    if not isinstance(task, dict):
        raise ConfigError(f"{path}: a top-level 'task' mapping is required")
    return _build_task(_merge_overrides(task, overrides))


def _read_yaml(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc


def _merge_overrides(task: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay CLI values on the config, routing each flag to the mapping that owns it."""
    merged = dict(task)
    generation = dict(merged.get("generation") or {})
    for key in TASK_OVERRIDES:
        if overrides.get(key) is not None:
            merged[key] = overrides[key]
    for key in GENERATION_OVERRIDES:
        if overrides.get(key) is not None:
            generation[key] = overrides[key]
    merged["generation"] = generation
    return merged


def _build_task(task: Mapping[str, Any]) -> TaskConfig:
    generation = _build_generation(task.get("generation") or {})
    return TaskConfig(
        name=str(task.get("name") or "task"),
        api_url=_require_str(task, "api_url").rstrip("/"),
        model=_require_str(task, "model"),
        rpm=_positive_int(task.get("rpm", DEFAULT_RPM), "task.rpm"),
        prompt=_build_prompt(task.get("prompt") or {}),
        generation=generation,
        evaluation=_build_evaluation(task.get("evaluation"), generation.scheme),
        output_field=_require_str(task, "output_field"),
    )


def _build_prompt(raw: Mapping[str, Any]) -> PromptConfig:
    system = raw.get("system")
    if system is not None and not isinstance(system, str):
        raise ConfigError("task.prompt.system must be a string")
    return PromptConfig(user=_require_str(raw, "user", prefix="task.prompt"), system=system)


def _build_generation(raw: Mapping[str, Any]) -> GenerationConfig:
    scheme = raw.get("scheme", DEFAULT_SCHEME)
    if scheme not in SCHEMES:
        raise ConfigError(f"task.generation.scheme must be one of: {', '.join(SCHEMES)}")
    temperature = _number(raw.get("temperature", 0.0), "task.generation.temperature")
    if scheme == "greedy":
        temperature = 0.0
    elif temperature <= 0:
        raise ConfigError(f"task.generation.temperature must be greater than 0 for the '{scheme}' scheme")
    return GenerationConfig(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_positive_int(raw.get("max_tokens", DEFAULT_MAX_TOKENS), "task.generation.max_tokens"),
        n=_positive_int(raw.get("n", 1), "task.generation.n"),
    )


def _build_evaluation(raw: Any, scheme: str) -> EvaluationConfig | None:
    """Validate the optional evaluation block, which rejection sampling requires."""
    if raw is None:
        if scheme == "rejection":
            raise ConfigError("task.evaluation is required for the 'rejection' scheme")
        return None
    if not isinstance(raw, dict):
        raise ConfigError("task.evaluation must be a mapping")

    evaluation_type = raw.get("type")
    if evaluation_type not in EVALUATION_TYPES:
        raise ConfigError(f"task.evaluation.type must be one of: {', '.join(EVALUATION_TYPES)}")
    extract = raw.get("extract", DEFAULT_EXTRACT)
    if extract not in EXTRACT_METHODS:
        raise ConfigError(f"task.evaluation.extract must be one of: {', '.join(EXTRACT_METHODS)}")

    answer_field = raw.get("answer_field")
    if evaluation_type in ANSWER_FIELD_TYPES and not isinstance(answer_field, str):
        raise ConfigError(f"task.evaluation.answer_field is required for '{evaluation_type}' evaluation")
    pattern = raw.get("pattern")
    if evaluation_type == "regex":
        pattern = _compiled_pattern(pattern)
    return EvaluationConfig(type=evaluation_type, extract=extract, answer_field=answer_field, pattern=pattern)


def _compiled_pattern(pattern: Any) -> str:
    if not isinstance(pattern, str):
        raise ConfigError("task.evaluation.pattern is required for 'regex' evaluation")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"task.evaluation.pattern is not a valid regular expression: {exc}") from exc
    return pattern


def _require_str(mapping: Mapping[str, Any], key: str, prefix: str = "task") -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{prefix}.{key} must be a non-empty string")
    return value


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{label} must be a positive integer")
    return value


def _number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise ConfigError(f"{label} must be a number")
    return float(value)
