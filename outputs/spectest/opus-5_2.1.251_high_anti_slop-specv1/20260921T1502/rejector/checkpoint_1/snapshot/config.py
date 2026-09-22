"""Task configuration: YAML loading, CLI override merging and validation."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from errors import UsageError

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex")
EXTRACT_METHODS = ("last_number", "last_line", "full")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_SCHEME = "greedy"
DEFAULT_EXTRACT = "full"

# CLI flag -> the key path inside the `task` mapping whose value it replaces.
OVERRIDE_PATHS = {
    "api_url": ("api_url",),
    "model": ("model",),
    "rpm": ("rpm",),
    "scheme": ("generation", "scheme"),
    "temperature": ("generation", "temperature"),
    "max_tokens": ("generation", "max_tokens"),
    "n": ("generation", "n"),
}


@dataclass(frozen=True)
class Prompt:
    """Message templates with `{field}` placeholders resolved per input row."""

    system: str | None
    user: str


@dataclass(frozen=True)
class Generation:
    """How responses are produced for a single row."""

    scheme: str
    temperature: float
    max_tokens: int
    n: int


@dataclass(frozen=True)
class Evaluation:
    """How a response is judged. `pattern` is compiled and only used by `regex`."""

    type: str
    answer_field: str | None
    extract: str
    pattern: re.Pattern[str] | None


@dataclass(frozen=True)
class TaskConfig:
    """A fully validated task definition."""

    name: str
    api_url: str
    model: str
    rpm: int
    prompt: Prompt
    generation: Generation
    evaluation: Evaluation | None
    output_field: str


def load_config(path: Path, overrides: dict[str, Any]) -> TaskConfig:
    """Read the YAML at `path`, apply non-None CLI overrides and validate the result."""
    try:
        document = yaml.safe_load(path.read_text())
    except OSError as error:
        raise UsageError(f"cannot read config {path}: {error.strerror}") from None
    except yaml.YAMLError as error:
        raise UsageError(f"invalid YAML in {path}: {error}") from None

    if not isinstance(document, dict) or not isinstance(document.get("task"), dict):
        raise UsageError(f"{path}: expected a top level 'task' mapping")

    return _build_task(_merge_overrides(document["task"], overrides))


def _merge_overrides(task: dict, overrides: dict[str, Any]) -> dict:
    """Return a copy of the `task` mapping with CLI values substituted in."""
    merged = deepcopy(task)
    for flag, value in overrides.items():
        if value is None:
            continue
        *parents, key = OVERRIDE_PATHS[flag]
        section = merged
        for parent in parents:
            section = _mapping(section, parent, f"task.{parent}")
        section[key] = value
    return merged


def _build_task(task: dict) -> TaskConfig:
    config = TaskConfig(
        name=str(_require(task, "name", "task")),
        api_url=str(_require(task, "api_url", "task")).rstrip("/"),
        model=str(_require(task, "model", "task")),
        rpm=_number(task.get("rpm", DEFAULT_RPM), "task.rpm", int, minimum=1),
        prompt=_build_prompt(_mapping(task, "prompt", "task.prompt")),
        generation=_build_generation(_mapping(task, "generation", "task.generation")),
        evaluation=_build_evaluation(task.get("evaluation")),
        output_field=str(_require(task, "output_field", "task")),
    )
    _validate(config)
    return config


def _build_prompt(section: dict) -> Prompt:
    system = section.get("system")
    return Prompt(
        system=None if system is None else str(system),
        user=str(_require(section, "user", "task.prompt")),
    )


def _build_generation(section: dict) -> Generation:
    scheme = str(section.get("scheme", DEFAULT_SCHEME))
    temperature = _number(
        section.get("temperature", 0.0), "task.generation.temperature", float, minimum=0.0
    )
    return Generation(
        scheme=scheme,
        # Greedy decoding ignores whatever temperature the config asked for.
        temperature=0.0 if scheme == "greedy" else temperature,
        max_tokens=_number(
            section.get("max_tokens", DEFAULT_MAX_TOKENS),
            "task.generation.max_tokens",
            int,
            minimum=1,
        ),
        n=_number(section.get("n", 1), "task.generation.n", int, minimum=1),
    )


def _build_evaluation(section: Any) -> Evaluation | None:
    if section is None:
        return None
    if not isinstance(section, dict):
        raise UsageError("task.evaluation must be a mapping")

    pattern = section.get("pattern")
    answer_field = section.get("answer_field")
    return Evaluation(
        type=str(_require(section, "type", "task.evaluation")),
        answer_field=None if answer_field is None else str(answer_field),
        extract=str(section.get("extract", DEFAULT_EXTRACT)),
        pattern=None if pattern is None else _compile(str(pattern)),
    )


def _validate(config: TaskConfig) -> None:
    """Enforce the cross field rules that the dataclasses cannot express."""
    generation, evaluation = config.generation, config.evaluation

    if generation.scheme not in SCHEMES:
        raise UsageError(
            f"task.generation.scheme must be one of {', '.join(SCHEMES)}; got '{generation.scheme}'"
        )
    if generation.scheme != "greedy" and generation.temperature <= 0:
        raise UsageError(
            f"task.generation.temperature must be > 0 for the '{generation.scheme}' scheme"
        )
    if generation.scheme == "rejection" and evaluation is None:
        raise UsageError("task.evaluation is required for the 'rejection' scheme")

    if evaluation is None:
        return
    if evaluation.type not in EVALUATION_TYPES:
        raise UsageError(
            f"task.evaluation.type must be one of {', '.join(EVALUATION_TYPES)}; got '{evaluation.type}'"
        )
    if evaluation.extract not in EXTRACT_METHODS:
        raise UsageError(
            f"task.evaluation.extract must be one of {', '.join(EXTRACT_METHODS)}; got '{evaluation.extract}'"
        )
    if evaluation.type == "regex" and evaluation.pattern is None:
        raise UsageError("task.evaluation.pattern is required for the 'regex' evaluation type")
    if evaluation.type != "regex" and evaluation.answer_field is None:
        raise UsageError(
            f"task.evaluation.answer_field is required for the '{evaluation.type}' evaluation type"
        )


def _require(section: dict, key: str, where: str) -> Any:
    """Fetch a mandatory config value."""
    if section.get(key) is None:
        raise UsageError(f"{where}.{key} is required")
    return section[key]


def _mapping(section: dict, key: str, where: str) -> dict:
    """Fetch an optional sub mapping, defaulting to an empty one."""
    value = section.setdefault(key, {})
    if not isinstance(value, dict):
        raise UsageError(f"{where} must be a mapping")
    return value


def _number(value: Any, where: str, cast: Callable[[Any], Any], minimum: float) -> Any:
    """Coerce a numeric config value and enforce its lower bound."""
    try:
        number = cast(value)
    except (TypeError, ValueError):
        raise UsageError(f"{where} must be a number; got '{value}'") from None
    if number < minimum:
        raise UsageError(f"{where} must be >= {minimum}; got {number}")
    return number


def _compile(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as error:
        raise UsageError(f"task.evaluation.pattern is not a valid regex: {error}") from None
