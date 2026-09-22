"""Task configuration: YAML loading, CLI overrides, and validation.

Two file layouts are accepted.  A top-level `task` mapping is the Part 1
single-task format; a `defaults` mapping plus a `tasks` mapping declares
several named tasks that each inherit from `defaults`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import ConfigError
from .extraction import EXTRACT_METHODS
from .icl import IclConfig, build_icl, check_examples
from .templates import placeholders

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_SUCCESS_EXIT_CODE = 0


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
    max_attempts: int | None = None

    @property
    def legacy_attempts(self) -> int:
        """Part 1 attempts per row; only rejection retries, and it retries `n` times."""
        return self.n if self.scheme == "rejection" else 1


@dataclass(frozen=True)
class Evaluation:
    """How a response is judged, and which part of it is compared."""

    type: str
    extract: str
    answer_field: str | None = None
    pattern: str | None = None
    command_template: str | None = None
    success_exit_code: int = DEFAULT_SUCCESS_EXIT_CODE
    judge_prompt: Prompt | None = None
    threshold: float | None = None
    model: str | None = None


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
    num_solutions: int = 1
    icl: IclConfig | None = None

    @property
    def list_format(self) -> bool:
        """Whether rows carry a list of solutions instead of a single one."""
        return self.icl is not None or self.num_solutions > 1

    @property
    def max_attempts(self) -> int:
        """Rejection's attempt budget: three tries per requested solution by default."""
        return self.generation.max_attempts or 3 * self.num_solutions

    @property
    def completions_url(self) -> str:
        return f"{self.api_url.rstrip('/')}/v1/chat/completions"

    @property
    def judge_model(self) -> str:
        """The model the judge calls for this task, defaulting to its own."""
        return (self.evaluation.model if self.evaluation else None) or self.model


@dataclass(frozen=True)
class RunConfig:
    """The tasks selected for this run, plus every name the config declares."""

    tasks: tuple[TaskConfig, ...]
    task_names: tuple[str | None, ...]
    multi: bool


def load_config(path: str | Path, overrides: dict, selected: list[str] | None = None) -> RunConfig:
    """Read a YAML config, apply CLI overrides, and validate the selected tasks.

    Only selected tasks are built: the spec asks for unselected tasks to be
    ignored for validation as well as execution.
    """
    path = Path(path)
    raw = _read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")
    if isinstance(raw.get("task"), dict):
        return _single_task_config(raw["task"], overrides, selected, path.parent)
    if isinstance(raw.get("tasks"), dict):
        return _multi_task_config(raw, overrides, selected, path.parent)
    raise ConfigError("config must contain a 'task' or a 'tasks' mapping")


def _read_yaml(path: Path):
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {exc}") from exc


def _single_task_config(
    task: dict, overrides: dict, selected: list[str] | None, config_dir: Path
) -> RunConfig:
    name = task.get("name")
    _reject_unknown(selected, [name])
    built = _build_task(_apply_overrides(task, overrides), name, "task", config_dir)
    return RunConfig(tasks=(built,), task_names=(name,), multi=False)


def _multi_task_config(
    raw: dict, overrides: dict, selected: list[str] | None, config_dir: Path
) -> RunConfig:
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("'defaults' must be a mapping")

    declared = list(raw["tasks"])
    _reject_unknown(selected, declared)
    names = list(selected) if selected else declared

    tasks = tuple(
        _build_task(
            _apply_overrides(_merge(defaults, _section(raw["tasks"], name)), overrides),
            name,
            f"tasks.{name}",
            config_dir,
        )
        for name in names
    )
    return RunConfig(tasks=tasks, task_names=tuple(declared), multi=True)


def _reject_unknown(selected: list[str] | None, declared: list[str | None]) -> None:
    unknown = [name for name in selected or () if name not in declared]
    if unknown:
        raise ConfigError(f"unknown task name(s): {', '.join(unknown)}")


def _merge(base: dict, override: dict) -> dict:
    """Layer `override` onto `base`; nested mappings merge, other values replace."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        merged[key] = (
            _merge(current, value) if isinstance(current, dict) and isinstance(value, dict) else value
        )
    return merged


def _apply_overrides(task: dict, overrides: dict) -> dict:
    """Layer the CLI overrides onto one task's raw mapping."""
    patch = {key: overrides[key] for key in ("api_url", "model", "rpm") if overrides.get(key) is not None}

    generation = {
        key: overrides[key]
        for key in ("scheme", "temperature", "max_tokens", "n")
        if overrides.get(key) is not None
    }
    if generation:
        patch["generation"] = generation

    if overrides.get("num_solutions") is not None:
        patch["num_solutions"] = overrides["num_solutions"]

    # The ICL flags only have something to re-point on a task that declares setups.
    icl = {
        key: overrides[f"icl_{key}"]
        for key in ("strategy", "k")
        if overrides.get(f"icl_{key}") is not None
    }
    if icl and task.get("icl") is not None:
        patch["icl"] = icl

    # --eval-model only has something to re-point on a task that runs a judge.
    if overrides.get("eval_model") is not None and _section(task, "evaluation").get("type") == "llm_judge":
        patch["evaluation"] = {"model": overrides["eval_model"]}

    return _merge(task, patch)


def _build_task(task: dict, name: str | None, label: str, config_dir: Path) -> TaskConfig:
    for key in ("api_url", "model", "prompt", "output_field"):
        if not task.get(key):
            raise ConfigError(f"{label}.{key} is required")

    generation = _build_generation(_section(task, "generation"), label)
    evaluation = _build_evaluation(task.get("evaluation"), label)
    if generation.scheme == "rejection" and evaluation is None:
        raise ConfigError(f"{label}.evaluation is required for the rejection scheme")

    prompt = _build_prompt(task["prompt"], f"{label}.prompt")
    icl = build_icl(task.get("icl"), config_dir, f"{label}.icl")
    if icl is not None:
        check_examples(icl, placeholders(prompt.user), f"{label}.icl")

    return TaskConfig(
        name=name,
        api_url=_require_str(task["api_url"], f"{label}.api_url"),
        model=_require_str(task["model"], f"{label}.model"),
        rpm=_require_positive_int(task.get("rpm", DEFAULT_RPM), f"{label}.rpm"),
        prompt=prompt,
        generation=generation,
        output_field=_require_str(task["output_field"], f"{label}.output_field"),
        evaluation=evaluation,
        num_solutions=_require_positive_int(
            task.get("num_solutions", 1), f"{label}.num_solutions"
        ),
        icl=icl,
    )


def _build_prompt(prompt, label: str) -> Prompt:
    if not isinstance(prompt, dict) or not prompt.get("user"):
        raise ConfigError(f"{label}.user is required")
    system = prompt.get("system")
    return Prompt(
        user=_require_str(prompt["user"], f"{label}.user"),
        system=None if system is None else _require_str(system, f"{label}.system"),
    )


def _build_generation(generation: dict, label: str) -> Generation:
    scheme = generation.get("scheme", "greedy")
    if scheme not in SCHEMES:
        raise ConfigError(f"unknown generation scheme '{scheme}'; expected one of {', '.join(SCHEMES)}")

    temperature = _require_float(generation.get("temperature", 0.0), f"{label}.generation.temperature")
    if scheme == "greedy":
        temperature = 0.0
    elif temperature <= 0:
        raise ConfigError(f"{label}.generation.temperature must be > 0 for the {scheme} scheme")

    max_attempts = generation.get("max_attempts")
    return Generation(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_require_positive_int(
            generation.get("max_tokens", DEFAULT_MAX_TOKENS), f"{label}.generation.max_tokens"
        ),
        n=_require_positive_int(generation.get("n", 1), f"{label}.generation.n"),
        max_attempts=(
            None
            if max_attempts is None
            else _require_positive_int(max_attempts, f"{label}.generation.max_attempts")
        ),
    )


def _build_evaluation(evaluation, label: str) -> Evaluation | None:
    """Validate one evaluation section; the keys checked depend on its type."""
    if evaluation is None:
        return None
    if not isinstance(evaluation, dict):
        raise ConfigError(f"{label}.evaluation must be a mapping")
    label = f"{label}.evaluation"

    eval_type = evaluation.get("type")
    if eval_type not in EVALUATION_TYPES:
        raise ConfigError(
            f"unknown evaluation type '{eval_type}'; expected one of {', '.join(EVALUATION_TYPES)}"
        )

    extract = evaluation.get("extract", "first_number" if eval_type == "llm_judge" else "full")
    if extract not in EXTRACT_METHODS:
        raise ConfigError(
            f"unknown extract method '{extract}'; expected one of {', '.join(EXTRACT_METHODS)}"
        )

    return Evaluation(
        type=eval_type,
        extract=extract,
        answer_field=_answer_field(evaluation, eval_type, label),
        pattern=_required_when(evaluation, "pattern", eval_type == "regex", label),
        command_template=_required_when(evaluation, "command_template", eval_type == "script", label),
        success_exit_code=_require_int(
            evaluation.get("success_exit_code", DEFAULT_SUCCESS_EXIT_CODE), f"{label}.success_exit_code"
        ),
        judge_prompt=_build_judge_prompt(evaluation, eval_type, label),
        threshold=_build_threshold(evaluation, eval_type, label),
        model=evaluation.get("model"),
    )


def _answer_field(evaluation: dict, eval_type: str, label: str) -> str | None:
    needed = eval_type in ("exact_match", "contains")
    return _required_when(evaluation, "answer_field", needed, label)


def _required_when(evaluation: dict, key: str, needed: bool, label: str) -> str | None:
    value = evaluation.get(key)
    if needed and not value:
        raise ConfigError(f"{label}.{key} is required for the {evaluation['type']} type")
    return None if value is None else _require_str(value, f"{label}.{key}")


def _build_judge_prompt(evaluation: dict, eval_type: str, label: str) -> Prompt | None:
    if eval_type != "llm_judge":
        return None
    if not isinstance(evaluation.get("judge_prompt"), dict):
        raise ConfigError(f"{label}.judge_prompt is required for the llm_judge type")
    return _build_prompt(evaluation["judge_prompt"], f"{label}.judge_prompt")


def _build_threshold(evaluation: dict, eval_type: str, label: str) -> float | None:
    if eval_type != "llm_judge":
        return None
    if "threshold" not in evaluation:
        raise ConfigError(f"{label}.threshold is required for the llm_judge type")
    return _require_float(evaluation["threshold"], f"{label}.threshold")


def _section(mapping: dict, key: str) -> dict:
    value = mapping.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' must be a mapping")
    return value


def _require_str(value, label: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be a string")
    return value


def _require_int(value, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{label} must be an integer")
    return value


def _require_positive_int(value, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{label} must be a positive integer")
    return value


def _require_float(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} must be a number")
    return float(value)
