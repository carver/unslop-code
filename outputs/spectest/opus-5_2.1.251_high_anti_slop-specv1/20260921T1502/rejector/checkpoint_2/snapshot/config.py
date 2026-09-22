"""Task configuration: YAML loading, CLI override merging and validation.

A config either defines a single task under a top level `task` key (the Part 1
format) or a `defaults` mapping plus a `tasks` mapping of named tasks. Both
shapes are loaded into the same `Suite` of validated `TaskConfig` objects.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import yaml

from errors import UsageError

SCHEMES = ("greedy", "sample", "rejection")
LOCAL_EVALUATIONS = ("exact_match", "contains", "regex")
EVALUATION_TYPES = LOCAL_EVALUATIONS + ("script", "llm_judge")
EXTRACT_METHODS = ("last_number", "first_number", "last_line", "letter", "full")
ANSWER_FIELD_TYPES = ("exact_match", "contains")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_SCHEME = "greedy"
DEFAULT_EXTRACT = "full"
DEFAULT_SUCCESS_EXIT_CODE = 0

# CLI flag -> the key path inside a task mapping whose value it replaces.
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
    """How a response is judged.

    Each field belongs to a subset of the types: `pattern` to `regex`,
    `judge_prompt`/`threshold`/`model` to `llm_judge`, and `command_template`/
    `success_exit_code` to `script`. `model` defaults to the task's model.
    """

    type: str
    answer_field: str | None
    extract: str
    pattern: re.Pattern[str] | None
    judge_prompt: Prompt | None
    threshold: float | None
    model: str
    command_template: str | None
    success_exit_code: int


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


@dataclass(frozen=True)
class Suite:
    """The tasks a run will execute.

    `multi` marks the multi task config format, which takes one input file and
    writes one output file per task.
    """

    tasks: list[TaskConfig]
    multi: bool


def load_config(path: Path, overrides: dict[str, Any], selected: Sequence[str] = ()) -> Suite:
    """Read the YAML at `path`, apply non-None CLI overrides and validate the result.

    `selected` narrows the suite to the named tasks; empty means every task.
    """
    try:
        document = yaml.safe_load(path.read_text())
    except OSError as error:
        raise UsageError(f"cannot read config {path}: {error.strerror}") from None
    except yaml.YAMLError as error:
        raise UsageError(f"invalid YAML in {path}: {error}") from None

    if not isinstance(document, dict):
        raise UsageError(f"{path}: expected a top level 'task' or 'tasks' mapping")
    if isinstance(document.get("task"), dict):
        return _single_suite(document["task"], overrides, selected)
    if isinstance(document.get("tasks"), dict):
        return _multi_suite(document, overrides, selected)
    raise UsageError(f"{path}: expected a top level 'task' or 'tasks' mapping")


def _single_suite(task: dict, overrides: dict[str, Any], selected: Sequence[str]) -> Suite:
    merged = _merge_overrides(task, overrides, "task")
    name = str(_require(merged, "name", "task"))
    _select([name], selected)
    return Suite([_build_task(merged, name, "task")], multi=False)


def _multi_suite(document: dict, overrides: dict[str, Any], selected: Sequence[str]) -> Suite:
    defaults = document.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise UsageError("defaults must be a mapping")

    tasks = document["tasks"]
    if not tasks:
        raise UsageError("tasks must define at least one task")

    configs = []
    for name in _select(list(tasks), selected):
        where = f"tasks.{name}"
        merged = _merge_overrides(_deep_merge(defaults, _mapping(tasks, name, where)), overrides, where)
        configs.append(_build_task(merged, name, where))
    return Suite(configs, multi=True)


def _select(available: list[str], selected: Sequence[str]) -> list[str]:
    """Narrow the config's task names to the `--task` selection, keeping config order."""
    unknown = [name for name in selected if name not in available]
    if unknown:
        raise UsageError(
            f"unknown task '{unknown[0]}'; the config defines {', '.join(available)}"
        )
    return [name for name in available if name in selected] if selected else available


def _deep_merge(defaults: dict, task: dict) -> dict:
    """Overlay `task` on `defaults`, merging sub mappings such as `generation` key by key."""
    merged = deepcopy(defaults)
    for key, value in task.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _merge_overrides(task: dict, overrides: dict[str, Any], where: str) -> dict:
    """Return a copy of the task mapping with CLI values substituted in."""
    merged = deepcopy(task)
    for flag, value in overrides.items():
        if value is None or flag == "eval_model":
            continue
        *parents, key = OVERRIDE_PATHS[flag]
        section = merged
        for parent in parents:
            section = _mapping(section, parent, f"{where}.{parent}")
        section[key] = value
    _apply_eval_model(merged, overrides.get("eval_model"))
    return merged


def _apply_eval_model(task: dict, model: str | None) -> None:
    """`--eval-model` retargets judge calls; tasks judged another way ignore it."""
    evaluation = task.get("evaluation")
    if model and isinstance(evaluation, dict) and evaluation.get("type") == "llm_judge":
        evaluation["model"] = model


def _build_task(task: dict, name: str, where: str) -> TaskConfig:
    model = str(_require(task, "model", where))
    config = TaskConfig(
        name=name,
        api_url=str(_require(task, "api_url", where)).rstrip("/"),
        model=model,
        rpm=_number(task.get("rpm", DEFAULT_RPM), f"{where}.rpm", int, minimum=1),
        prompt=_build_prompt(_mapping(task, "prompt", f"{where}.prompt"), f"{where}.prompt"),
        generation=_build_generation(
            _mapping(task, "generation", f"{where}.generation"), f"{where}.generation"
        ),
        evaluation=_build_evaluation(task.get("evaluation"), f"{where}.evaluation", model),
        output_field=str(_require(task, "output_field", where)),
    )
    _validate(config, where)
    return config


def _build_prompt(section: dict, where: str) -> Prompt:
    system = section.get("system")
    return Prompt(
        system=None if system is None else str(system),
        user=str(_require(section, "user", where)),
    )


def _build_generation(section: dict, where: str) -> Generation:
    scheme = str(section.get("scheme", DEFAULT_SCHEME))
    temperature = _number(section.get("temperature", 0.0), f"{where}.temperature", float, minimum=0.0)
    return Generation(
        scheme=scheme,
        # Greedy decoding ignores whatever temperature the config asked for.
        temperature=0.0 if scheme == "greedy" else temperature,
        max_tokens=_number(
            section.get("max_tokens", DEFAULT_MAX_TOKENS), f"{where}.max_tokens", int, minimum=1
        ),
        n=_number(section.get("n", 1), f"{where}.n", int, minimum=1),
    )


def _build_evaluation(section: Any, where: str, model: str) -> Evaluation | None:
    if section is None:
        return None
    if not isinstance(section, dict):
        raise UsageError(f"{where} must be a mapping")

    pattern = section.get("pattern")
    answer_field = section.get("answer_field")
    threshold = section.get("threshold")
    command_template = section.get("command_template")
    return Evaluation(
        type=str(_require(section, "type", where)),
        answer_field=None if answer_field is None else str(answer_field),
        extract=str(section.get("extract", DEFAULT_EXTRACT)),
        pattern=None if pattern is None else _compile(str(pattern), where),
        judge_prompt=_judge_prompt(section, f"{where}.judge_prompt"),
        threshold=None if threshold is None else _number(threshold, f"{where}.threshold", float),
        model=str(section.get("model", model)),
        command_template=None if command_template is None else str(command_template),
        success_exit_code=_number(
            section.get("success_exit_code", DEFAULT_SUCCESS_EXIT_CODE),
            f"{where}.success_exit_code",
            int,
            minimum=0,
        ),
    )


def _judge_prompt(section: dict, where: str) -> Prompt | None:
    """The `llm_judge` prompt, which follows the same template rules as the task prompt."""
    if section.get("judge_prompt") is None:
        return None
    return _build_prompt(_mapping(section, "judge_prompt", where), where)


def _validate(config: TaskConfig, where: str) -> None:
    """Enforce the cross field rules that the dataclasses cannot express."""
    generation, evaluation = config.generation, config.evaluation

    if generation.scheme not in SCHEMES:
        raise UsageError(
            f"{where}.generation.scheme must be one of {', '.join(SCHEMES)}; got '{generation.scheme}'"
        )
    if generation.scheme != "greedy" and generation.temperature <= 0:
        raise UsageError(
            f"{where}.generation.temperature must be > 0 for the '{generation.scheme}' scheme"
        )
    if generation.scheme == "rejection" and evaluation is None:
        raise UsageError(f"{where}.evaluation is required for the 'rejection' scheme")

    if evaluation is not None:
        _validate_evaluation(evaluation, f"{where}.evaluation")


def _validate_evaluation(evaluation: Evaluation, where: str) -> None:
    if evaluation.type not in EVALUATION_TYPES:
        raise UsageError(
            f"{where}.type must be one of {', '.join(EVALUATION_TYPES)}; got '{evaluation.type}'"
        )
    if evaluation.extract not in EXTRACT_METHODS:
        raise UsageError(
            f"{where}.extract must be one of {', '.join(EXTRACT_METHODS)}; got '{evaluation.extract}'"
        )
    if evaluation.type == "regex" and evaluation.pattern is None:
        raise UsageError(f"{where}.pattern is required for the 'regex' evaluation type")
    if evaluation.type in ANSWER_FIELD_TYPES and evaluation.answer_field is None:
        raise UsageError(
            f"{where}.answer_field is required for the '{evaluation.type}' evaluation type"
        )
    if evaluation.type == "script" and evaluation.command_template is None:
        raise UsageError(f"{where}.command_template is required for the 'script' evaluation type")
    if evaluation.type == "llm_judge" and evaluation.judge_prompt is None:
        raise UsageError(f"{where}.judge_prompt is required for the 'llm_judge' evaluation type")
    if evaluation.type == "llm_judge" and evaluation.threshold is None:
        raise UsageError(f"{where}.threshold is required for the 'llm_judge' evaluation type")


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


def _number(
    value: Any, where: str, cast: Callable[[Any], Any], minimum: float = float("-inf")
) -> Any:
    """Coerce a numeric config value and enforce its lower bound."""
    try:
        number = cast(value)
    except (TypeError, ValueError):
        raise UsageError(f"{where} must be a number; got '{value}'") from None
    if number < minimum:
        raise UsageError(f"{where} must be >= {minimum}; got {number}")
    return number


def _compile(pattern: str, where: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as error:
        raise UsageError(f"{where}.pattern is not a valid regex: {error}") from None
