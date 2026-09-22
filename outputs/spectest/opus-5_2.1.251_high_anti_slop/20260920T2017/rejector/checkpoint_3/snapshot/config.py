"""Loading and validation of the YAML task configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from errors import ConfigError
from icl import DEFAULT_STRATEGY, STRATEGIES, IclConfig, IclExample, IclSetup, load_examples

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex", "llm_judge", "script")
EXTRACT_METHODS = ("last_number", "first_number", "last_line", "letter", "full")

DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 512
DEFAULT_EXTRACT = "full"
#: Judges answer with a score, so their responses are read as numbers by default.
DEFAULT_JUDGE_EXTRACT = "first_number"
DEFAULT_SUCCESS_EXIT_CODE = 0
DEFAULT_NUM_SOLUTIONS = 1
#: Rejection attempts allowed per requested solution when `max_attempts` is unset.
ATTEMPTS_PER_SOLUTION = 3

#: CLI flag name -> (config section, key). A None section writes at task level.
CLI_OVERRIDES = {
    "api_url": (None, "api_url"),
    "model": (None, "model"),
    "rpm": (None, "rpm"),
    "scheme": ("generation", "scheme"),
    "temperature": ("generation", "temperature"),
    "max_tokens": ("generation", "max_tokens"),
    "n": ("generation", "n"),
    "eval_model": ("evaluation", "model"),
    "num_solutions": (None, "num_solutions"),
    "icl_strategy": ("icl", "strategy"),
    "icl_k": ("icl", "k"),
}

#: Sections a task only has if it declares them; an override cannot conjure one.
OPTIONAL_SECTIONS = ("evaluation", "icl")


@dataclass(frozen=True)
class PromptConfig:
    """Prompt templates with `{field}` placeholders resolved per input row."""

    system: str
    user: str


@dataclass(frozen=True)
class GenerationConfig:
    """Sampling parameters for one scheme.

    `n` is the number of rejection-sampling attempts a single-solution task
    makes; it is normalised to 1 for the `greedy` and `sample` schemes, which
    always make a single attempt. `max_attempts` replaces it as the rejection
    budget once a task asks for several solutions or uses ICL.
    """

    scheme: str
    temperature: float
    max_tokens: int
    n: int
    max_attempts: int


@dataclass(frozen=True)
class EvaluationConfig:
    """How a response is judged.

    Only the fields its `type` uses are populated: `answer_field` names a field
    of the input row, `pattern` holds the `regex` expression, `judge_prompt`,
    `threshold` and `model` drive an `llm_judge` call, and `command_template`
    with `success_exit_code` drive a `script` run.
    """

    type: str
    extract: str
    answer_field: str | None = None
    pattern: str | None = None
    judge_prompt: PromptConfig | None = None
    threshold: float | None = None
    model: str | None = None
    command_template: str | None = None
    success_exit_code: int = DEFAULT_SUCCESS_EXIT_CODE


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
    num_solutions: int = DEFAULT_NUM_SOLUTIONS
    icl: IclConfig | None = None

    @property
    def list_output(self) -> bool:
        """Whether a row reports a list of solutions rather than a single one.

        ICL or a request for several solutions switches the record format; a
        plain single-solution task keeps the original one.
        """
        return self.icl is not None or self.num_solutions > 1


@dataclass(frozen=True)
class RunConfig:
    """The tasks a run will execute, in config order.

    `multi` records which config format declared them, which decides whether
    `--input`/`--output` name files or a task-keyed set of them.
    """

    tasks: list[TaskConfig]
    multi: bool


def load_config(
    path: str, overrides: dict[str, Any] | None = None, selected: list[str] | None = None
) -> RunConfig:
    """Read the config, apply CLI overrides, and validate the selected tasks.

    `selected` names the tasks to keep; unselected tasks are dropped before
    validation, so a run of one task is not held up by another's mistakes.

    Raises:
        ConfigError: the file is unreadable or the configuration is invalid.
    """
    document = _read_document(path)
    bodies, multi = _task_bodies(document, path)
    bodies = {name: _apply_overrides(body, overrides or {}) for name, body in bodies.items()}
    base_dir = Path(path).parent
    return RunConfig(
        tasks=[
            _build_task(body, name, f"tasks.{name}" if multi else "task", base_dir)
            for name, body in _select(bodies, selected, path).items()
        ],
        multi=multi,
    )


def overrides_from_flags(flags: dict[str, Any]) -> dict[str, Any]:
    """Shape the CLI flags that were actually given into a config-shaped overlay."""
    overlay: dict[str, Any] = {}
    for flag, (section, key) in CLI_OVERRIDES.items():
        if flags.get(flag) is None:
            continue
        target = overlay.setdefault(section, {}) if section else overlay
        target[key] = flags[flag]
    return overlay


def _read_document(path: str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(Path(path).read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"cannot parse config {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError(f"config {path} must be a mapping")
    return document


def _task_bodies(document: dict[str, Any], path: str) -> tuple[dict[str, dict[str, Any]], bool]:
    """Return the raw body of each task by name, and whether the config is multi-task.

    A multi-task config layers every task on top of the shared `defaults`; the
    single-task `task` key keeps its own `name` field.
    """
    if isinstance(document.get("task"), dict):
        task = document["task"]
        return {_require(task, "name", str, "task"): task}, False
    if not isinstance(document.get("tasks"), dict):
        raise ConfigError(f"config {path} must contain a 'task' or 'tasks' mapping")
    defaults = _optional(document, "defaults", dict, {}, "config")
    return {
        name: _merge(defaults, _checked(body, dict, f"tasks.{name}"))
        for name, body in document["tasks"].items()
    }, True


def _select(
    bodies: dict[str, dict[str, Any]], selected: list[str] | None, path: str
) -> dict[str, dict[str, Any]]:
    if not selected:
        return bodies
    unknown = [name for name in selected if name not in bodies]
    if unknown:
        raise ConfigError(f"config {path} has no task named '{unknown[0]}'")
    return {name: body for name, body in bodies.items() if name in selected}


def _apply_overrides(task: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Overlay the CLI values, skipping sections this task does not declare.

    A judge model only reaches tasks that evaluate, and an ICL flag only tasks
    that configure ICL; neither creates the section it names.
    """
    overrides = {
        key: value
        for key, value in overrides.items()
        if key not in OPTIONAL_SECTIONS or isinstance(task.get(key), dict)
    }
    return _merge(task, overrides)


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Overlay one mapping onto another, merging nested sections key by key."""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        merged[key] = _merge(current, value) if isinstance(current, dict) and isinstance(value, dict) else value
    return merged


def _build_task(task: dict[str, Any], name: str, where: str, base_dir: Path) -> TaskConfig:
    prompt = _require(task, "prompt", dict, where)
    rpm = _require(task, "rpm", int, where)
    if rpm <= 0:
        raise ConfigError(f"{where}.rpm must be > 0")
    model = _require(task, "model", str, where)
    num_solutions = _optional(task, "num_solutions", int, DEFAULT_NUM_SOLUTIONS, where)
    if num_solutions < 1:
        raise ConfigError(f"{where}.num_solutions must be >= 1")
    generation = _build_generation(
        _optional(task, "generation", dict, {}, where), num_solutions, f"{where}.generation"
    )
    return TaskConfig(
        name=name,
        api_url=_require(task, "api_url", str, where),
        model=model,
        rpm=rpm,
        prompt=PromptConfig(
            system=_require(prompt, "system", str, f"{where}.prompt"),
            user=_require(prompt, "user", str, f"{where}.prompt"),
        ),
        generation=generation,
        evaluation=_build_evaluation(task.get("evaluation"), generation.scheme, model, f"{where}.evaluation"),
        output_field=_require(task, "output_field", str, where),
        num_solutions=num_solutions,
        icl=_build_icl(task.get("icl"), base_dir, f"{where}.icl"),
    )


def _build_generation(
    generation: dict[str, Any], num_solutions: int, where: str
) -> GenerationConfig:
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

    default_budget = ATTEMPTS_PER_SOLUTION * num_solutions
    max_attempts = _optional(generation, "max_attempts", int, default_budget, where)
    if max_attempts < 1:
        raise ConfigError(f"{where}.max_attempts must be >= 1")

    return GenerationConfig(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_optional(generation, "max_tokens", int, DEFAULT_MAX_TOKENS, where),
        n=n if scheme == "rejection" else 1,
        max_attempts=max_attempts,
    )


def _build_icl(icl: Any, base_dir: Path, where: str) -> IclConfig | None:
    """Read the task's ICL setups, loading any that live in their own file."""
    if icl is None:
        return None
    if not isinstance(icl, dict):
        raise ConfigError(f"{where} must be a mapping")

    strategy = _optional(icl, "strategy", str, DEFAULT_STRATEGY, where)
    if strategy not in STRATEGIES:
        raise ConfigError(f"{where}.strategy must be one of {', '.join(STRATEGIES)}")
    k = _optional(icl, "k", int, None, where)
    if k is not None and k < 1:
        raise ConfigError(f"{where}.k must be >= 1")

    setups = _require(icl, "setups", list, where)
    if not setups:
        raise ConfigError(f"{where}.setups must not be empty")
    return IclConfig(
        setups=tuple(
            _build_setup(setup, base_dir, f"{where}.setups[{index}]")
            for index, setup in enumerate(setups)
        ),
        strategy=strategy,
        k=k,
    )


def _build_setup(setup: Any, base_dir: Path, where: str) -> IclSetup:
    """A setup lists its examples inline or names a JSONL file beside the config."""
    _checked(setup, dict, where)
    name = _require(setup, "name", str, where)
    if ("examples" in setup) == ("file" in setup):
        raise ConfigError(f"{where} must have exactly one of 'examples' or 'file'")
    if "file" in setup:
        path = base_dir / _require(setup, "file", str, where)
        return IclSetup(name=name, examples=load_examples(path, where))
    return IclSetup(name=name, examples=_inline_examples(_require(setup, "examples", list, where), where))


def _inline_examples(examples: list[Any], where: str) -> tuple[IclExample, ...]:
    if not examples:
        raise ConfigError(f"{where}.examples must not be empty")
    parsed = []
    for index, example in enumerate(examples):
        at = f"{where}.examples[{index}]"
        _checked(example, dict, at)
        parsed.append(
            IclExample(
                input=_require(example, "input", dict, at),
                output=_require(example, "output", str, at),
            )
        )
    return tuple(parsed)


def _build_evaluation(
    evaluation: Any, scheme: str, model: str, where: str
) -> EvaluationConfig | None:
    if evaluation is None:
        if scheme == "rejection":
            raise ConfigError(f"{where} is required for scheme 'rejection'")
        return None
    if not isinstance(evaluation, dict):
        raise ConfigError(f"{where} must be a mapping")

    kind = _require(evaluation, "type", str, where)
    if kind not in EVALUATION_TYPES:
        raise ConfigError(f"{where}.type must be one of {', '.join(EVALUATION_TYPES)}")
    default_extract = DEFAULT_JUDGE_EXTRACT if kind == "llm_judge" else DEFAULT_EXTRACT
    extract = _optional(evaluation, "extract", str, default_extract, where)
    if extract not in EXTRACT_METHODS:
        raise ConfigError(f"{where}.extract must be one of {', '.join(EXTRACT_METHODS)}")

    return EvaluationConfig(type=kind, extract=extract, **_TYPE_FIELDS[kind](evaluation, model, where))


def _answer_fields(evaluation: dict[str, Any], model: str, where: str) -> dict[str, Any]:
    return {"answer_field": _require(evaluation, "answer_field", str, where)}


def _regex_fields(evaluation: dict[str, Any], model: str, where: str) -> dict[str, Any]:
    pattern = _require(evaluation, "pattern", str, where)
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"{where}.pattern is not a valid regex: {exc}") from exc
    return {"pattern": pattern}


def _judge_fields(evaluation: dict[str, Any], model: str, where: str) -> dict[str, Any]:
    """The judge falls back to the task's own model when it names none."""
    judge_prompt = _require(evaluation, "judge_prompt", dict, where)
    return {
        "judge_prompt": PromptConfig(
            system=_require(judge_prompt, "system", str, f"{where}.judge_prompt"),
            user=_require(judge_prompt, "user", str, f"{where}.judge_prompt"),
        ),
        "threshold": float(_require(evaluation, "threshold", (int, float), where)),
        "model": _optional(evaluation, "model", str, model, where),
    }


def _script_fields(evaluation: dict[str, Any], model: str, where: str) -> dict[str, Any]:
    return {
        "command_template": _require(evaluation, "command_template", str, where),
        "success_exit_code": _optional(
            evaluation, "success_exit_code", int, DEFAULT_SUCCESS_EXIT_CODE, where
        ),
    }


#: The extra `EvaluationConfig` fields each evaluation type requires.
_TYPE_FIELDS = {
    "exact_match": _answer_fields,
    "contains": _answer_fields,
    "regex": _regex_fields,
    "llm_judge": _judge_fields,
    "script": _script_fields,
}


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
