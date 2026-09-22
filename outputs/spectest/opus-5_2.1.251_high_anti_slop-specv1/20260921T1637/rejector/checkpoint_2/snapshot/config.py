"""Task configuration: YAML loading, CLI override merging, and validation.

Two file layouts are accepted. A top-level ``task`` mapping is the single-task
format; a ``tasks`` mapping (optionally alongside ``defaults``) defines several
named tasks that each override the shared defaults.
"""

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import yaml

from errors import ConfigError

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex", "llm_judge", "script")
EXTRACT_METHODS = ("last_number", "first_number", "last_line", "letter", "full")
ANSWER_FIELD_TYPES = ("exact_match", "contains")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_SCHEME = "greedy"
DEFAULT_EXTRACT = "full"
#: A judge reply is turned into a number, so it extracts one unless told otherwise.
DEFAULT_JUDGE_EXTRACT = "first_number"
DEFAULT_SUCCESS_EXIT_CODE = 0

#: CLI overrides that replace values on a task mapping.
TASK_OVERRIDES = ("api_url", "model", "rpm")
#: CLI overrides that replace values on a task's ``generation`` mapping.
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
    """How a response is judged to pass or fail.

    Only the fields belonging to ``type`` are populated: ``pattern`` for
    ``regex``, ``judge_prompt`` / ``judge_model`` / ``threshold`` for
    ``llm_judge``, and ``command_template`` / ``success_exit_code`` for
    ``script``.
    """

    type: str
    extract: str
    answer_field: str | None = None
    pattern: str | None = None
    judge_prompt: PromptConfig | None = None
    judge_model: str | None = None
    threshold: float | None = None
    command_template: str | None = None
    success_exit_code: int = DEFAULT_SUCCESS_EXIT_CODE


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


@dataclass(frozen=True)
class RunConfig:
    """Every task a config file defines, plus which of the two layouts it used."""

    tasks: tuple[TaskConfig, ...]
    multi: bool


def load_config(path: str, overrides: Mapping[str, Any]) -> RunConfig:
    """Read the YAML config at ``path``, apply non-``None`` overrides, and validate every task."""
    document = _read_yaml(path)
    document = document if isinstance(document, dict) else {}
    if isinstance(document.get("task"), dict):
        return RunConfig((_build_single(document["task"], overrides),), multi=False)
    if isinstance(document.get("tasks"), dict):
        return RunConfig(_build_multi(document, overrides, path), multi=True)
    raise ConfigError(f"{path}: a top-level 'task' or 'tasks' mapping is required")


def _read_yaml(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc


def _build_single(raw: Mapping[str, Any], overrides: Mapping[str, Any]) -> TaskConfig:
    """Build the one task of a Part 1 style config, whose name comes from ``task.name``."""
    return _build_task(_merge_overrides(raw, overrides), str(raw.get("name") or "task"), "task")


def _build_multi(
    document: Mapping[str, Any], overrides: Mapping[str, Any], path: str
) -> tuple[TaskConfig, ...]:
    """Build every named task, each one layered on top of the shared ``defaults``."""
    defaults = document.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError(f"{path}: 'defaults' must be a mapping")
    tasks = document["tasks"]
    if not tasks:
        raise ConfigError(f"{path}: 'tasks' must define at least one task")

    built = []
    for name, raw in tasks.items():
        if not isinstance(raw, dict):
            raise ConfigError(f"tasks.{name} must be a mapping")
        merged = _merge_overrides(_deep_merge(defaults, raw), overrides)
        built.append(_build_task(merged, str(name), f"tasks.{name}"))
    return tuple(built)


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay one mapping on another, merging nested sections such as ``prompt`` key by key."""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        mergeable = isinstance(current, dict) and isinstance(value, dict)
        merged[key] = _deep_merge(current, value) if mergeable else value
    return merged


def _merge_overrides(task: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay CLI values on a task, routing each flag to the mapping that owns it."""
    merged = dict(task)
    generation = dict(merged.get("generation") or {})
    for key in TASK_OVERRIDES:
        if overrides.get(key) is not None:
            merged[key] = overrides[key]
    for key in GENERATION_OVERRIDES:
        if overrides.get(key) is not None:
            generation[key] = overrides[key]
    merged["generation"] = generation

    evaluation = merged.get("evaluation")
    if overrides.get("eval_model") is not None and isinstance(evaluation, dict):
        merged["evaluation"] = {**evaluation, "model": overrides["eval_model"]}
    return merged


def _build_task(task: Mapping[str, Any], name: str, label: str) -> TaskConfig:
    """Validate one merged task mapping, reporting problems under ``label``."""
    model = _require_str(task, "model", label)
    generation = _build_generation(task.get("generation") or {}, label)
    return TaskConfig(
        name=name,
        api_url=_require_str(task, "api_url", label).rstrip("/"),
        model=model,
        rpm=_positive_int(task.get("rpm", DEFAULT_RPM), f"{label}.rpm"),
        prompt=_build_prompt(task.get("prompt") or {}, f"{label}.prompt"),
        generation=generation,
        evaluation=_build_evaluation(task.get("evaluation"), generation.scheme, model, label),
        output_field=_require_str(task, "output_field", label),
    )


def _build_prompt(raw: Mapping[str, Any], label: str) -> PromptConfig:
    system = raw.get("system")
    if system is not None and not isinstance(system, str):
        raise ConfigError(f"{label}.system must be a string")
    return PromptConfig(user=_require_str(raw, "user", label), system=system)


def _build_generation(raw: Mapping[str, Any], label: str) -> GenerationConfig:
    scheme = raw.get("scheme", DEFAULT_SCHEME)
    if scheme not in SCHEMES:
        raise ConfigError(f"{label}.generation.scheme must be one of: {', '.join(SCHEMES)}")
    temperature = _number(raw.get("temperature", 0.0), f"{label}.generation.temperature")
    if scheme == "greedy":
        temperature = 0.0
    elif temperature <= 0:
        raise ConfigError(f"{label}.generation.temperature must be greater than 0 for the '{scheme}' scheme")
    return GenerationConfig(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_positive_int(raw.get("max_tokens", DEFAULT_MAX_TOKENS), f"{label}.generation.max_tokens"),
        n=_positive_int(raw.get("n", 1), f"{label}.generation.n"),
    )


def _build_evaluation(raw: Any, scheme: str, model: str, label: str) -> EvaluationConfig | None:
    """Validate the optional evaluation block, which rejection sampling requires."""
    if raw is None:
        if scheme == "rejection":
            raise ConfigError(f"{label}.evaluation is required for the 'rejection' scheme")
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{label}.evaluation must be a mapping")

    prefix = f"{label}.evaluation"
    evaluation_type = raw.get("type")
    if evaluation_type not in EVALUATION_TYPES:
        raise ConfigError(f"{prefix}.type must be one of: {', '.join(EVALUATION_TYPES)}")
    default_extract = DEFAULT_JUDGE_EXTRACT if evaluation_type == "llm_judge" else DEFAULT_EXTRACT
    extract = raw.get("extract", default_extract)
    if extract not in EXTRACT_METHODS:
        raise ConfigError(f"{prefix}.extract must be one of: {', '.join(EXTRACT_METHODS)}")

    answer_field = raw.get("answer_field")
    if evaluation_type in ANSWER_FIELD_TYPES and not isinstance(answer_field, str):
        raise ConfigError(f"{prefix}.answer_field is required for '{evaluation_type}' evaluation")

    extras = _TYPE_FIELDS.get(evaluation_type)
    return EvaluationConfig(
        type=evaluation_type,
        extract=extract,
        answer_field=answer_field,
        **(extras(raw, model, prefix) if extras else {}),
    )


def _regex_fields(raw: Mapping[str, Any], model: str, prefix: str) -> dict[str, Any]:
    """The ``regex`` extra: a pattern that must compile."""
    pattern = raw.get("pattern")
    if not isinstance(pattern, str):
        raise ConfigError(f"{prefix}.pattern is required for 'regex' evaluation")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"{prefix}.pattern is not a valid regular expression: {exc}") from exc
    return {"pattern": pattern}


def _judge_fields(raw: Mapping[str, Any], model: str, prefix: str) -> dict[str, Any]:
    """The ``llm_judge`` extras: the judge's prompt, its model, and the passing threshold."""
    judge_prompt = raw.get("judge_prompt")
    if not isinstance(judge_prompt, dict):
        raise ConfigError(f"{prefix}.judge_prompt is required for 'llm_judge' evaluation")
    judge_model = raw.get("model", model)
    if not isinstance(judge_model, str) or not judge_model.strip():
        raise ConfigError(f"{prefix}.model must be a non-empty string")
    return {
        "judge_prompt": _build_prompt(judge_prompt, f"{prefix}.judge_prompt"),
        "judge_model": judge_model,
        "threshold": _number(raw.get("threshold"), f"{prefix}.threshold"),
    }


def _script_fields(raw: Mapping[str, Any], model: str, prefix: str) -> dict[str, Any]:
    """The ``script`` extras: the shell command and the exit code that counts as a pass."""
    command = raw.get("command_template")
    if not isinstance(command, str) or not command.strip():
        raise ConfigError(f"{prefix}.command_template is required for 'script' evaluation")
    exit_code = raw.get("success_exit_code", DEFAULT_SUCCESS_EXIT_CODE)
    if not isinstance(exit_code, int):
        raise ConfigError(f"{prefix}.success_exit_code must be an integer")
    return {"command_template": command, "success_exit_code": exit_code}


def _require_str(mapping: Mapping[str, Any], key: str, prefix: str) -> str:
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


#: Per-type validators for the evaluation fields that only some types use.
_TYPE_FIELDS: dict[str, Callable[[Mapping[str, Any], str, str], dict[str, Any]]] = {
    "regex": _regex_fields,
    "llm_judge": _judge_fields,
    "script": _script_fields,
}
