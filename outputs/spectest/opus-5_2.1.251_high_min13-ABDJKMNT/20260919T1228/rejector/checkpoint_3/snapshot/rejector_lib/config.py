"""Loading, merging, and validating the YAML task configuration.

A config file is either the Part 1 single-task shape (a top-level `task`
mapping) or the Part 2 multi-task shape (`defaults` plus a `tasks` mapping).
Both are read into a `RawConfig`, which builds a validated `TaskConfig` for
each task the run actually selects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import ConfigError
from .icl import IclConfig, build_icl

SCHEMES = ("greedy", "sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")
ANSWER_FIELD_TYPES = ("exact_match", "contains")

DEFAULT_RPM = 60
DEFAULT_MAX_TOKENS = 512
DEFAULT_TASK_NAME = "task"
DEFAULT_EXTRACT = "full"
JUDGE_EXTRACT = "first_number"
DEFAULT_SOLUTIONS = 1
ATTEMPTS_PER_SOLUTION = 3


@dataclass(frozen=True)
class ScriptConfig:
    """The shell command a `script` evaluation runs, and its passing exit code."""

    command_template: str
    success_exit_code: int


@dataclass(frozen=True)
class JudgeConfig:
    """The second-model scoring call behind an `llm_judge` evaluation."""

    system_template: str | None
    user_template: str
    threshold: float
    model: str | None


@dataclass(frozen=True)
class EvaluationConfig:
    type: str
    answer_field: str | None = None
    extract: str = DEFAULT_EXTRACT
    pattern: str | None = None
    script: ScriptConfig | None = None
    judge: JudgeConfig | None = None


@dataclass(frozen=True)
class GenerationConfig:
    scheme: str
    temperature: float
    max_tokens: int
    n: int
    max_attempts: int | None = None


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
    num_solutions: int = DEFAULT_SOLUTIONS
    icl: IclConfig | None = None

    @property
    def list_format(self) -> bool:
        """Whether rows carry lists of solutions rather than the Part 1 shape."""
        return self.icl is not None or self.num_solutions > 1

    @property
    def max_attempts(self) -> int:
        """The rejection attempt budget, defaulted from `num_solutions`."""
        return (
            self.generation.max_attempts
            or ATTEMPTS_PER_SOLUTION * self.num_solutions
        )

    @property
    def answer_field(self) -> str | None:
        """The input field the evaluation compares against, if any."""
        return self.evaluation.answer_field if self.evaluation else None

    @property
    def judge(self) -> JudgeConfig | None:
        """The judge settings, for `llm_judge` tasks only."""
        return self.evaluation.judge if self.evaluation else None

    @property
    def judge_model(self) -> str | None:
        """The model judge calls use: `evaluation.model`, else the task's."""
        return None if self.judge is None else (self.judge.model or self.model)


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
    eval_model: str | None = None
    num_solutions: int | None = None
    icl_strategy: str | None = None
    icl_k: int | None = None

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
        if self.num_solutions is not None:
            merged["num_solutions"] = self.num_solutions
        merged.update(self._icl_overrides(merged.get("icl")))

        evaluation = merged.get("evaluation")
        if self.eval_model and _is_judge(evaluation):
            merged["evaluation"] = {**evaluation, "model": self.eval_model}
        return merged

    def _icl_overrides(self, icl) -> dict:
        """The ICL flags only mean something to a task that configures ICL."""
        if not isinstance(icl, dict):
            return {}
        chosen = {"strategy": self.icl_strategy, "k": self.icl_k}
        return {"icl": {**icl, **{k: v for k, v in chosen.items() if v is not None}}}


@dataclass(frozen=True)
class RawConfig:
    """Task settings read from the file, merged with `defaults` but unvalidated.

    Validation is deferred to `build` so that tasks left out by `--task` never
    have to be well-formed.
    """

    multi: bool
    tasks: dict[str, dict]
    directory: Path

    def build(self, name: str, overrides: Overrides) -> TaskConfig:
        """Validate one task into a `TaskConfig`."""
        try:
            return _build_task(
                name, overrides.applied_to(self.tasks[name]), self.directory
            )
        except ConfigError as exc:
            if not self.multi:
                raise
            raise ConfigError(f"task {name!r}: {exc}") from exc


def load_config(path: Path) -> RawConfig:
    """Read the config file and merge `defaults` into each task it declares."""
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")
    directory = path.parent
    if isinstance(raw.get("task"), dict):
        task = raw["task"]
        name = str(task.get("name", DEFAULT_TASK_NAME))
        return RawConfig(False, {name: task}, directory)
    return RawConfig(True, _merged_tasks(raw), directory)


def _merged_tasks(raw: dict) -> dict[str, dict]:
    """Apply `defaults` to every entry of a multi-task `tasks` mapping."""
    tasks = raw.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        raise ConfigError("config must contain a 'task' mapping or a 'tasks' mapping")

    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ConfigError("config 'defaults' must be a mapping")

    merged = {}
    for name, settings in tasks.items():
        if not isinstance(settings, dict):
            raise ConfigError(f"task {name!r} must be a mapping")
        merged[str(name)] = _deep_merge(defaults, settings)
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge nested mappings key by key; anything else in `override` wins."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _build_task(name: str, task: dict, config_dir: Path) -> TaskConfig:
    """Validate one task's settings, which already include `defaults`."""
    generation = _build_generation(task.get("generation"))
    system_template, user_template = _prompt_templates(task.get("prompt"), "task.prompt")
    return TaskConfig(
        name=name,
        api_url=_require_text(task, "api_url").rstrip("/"),
        model=_require_text(task, "model"),
        rpm=_positive_int(task.get("rpm", DEFAULT_RPM), "rpm"),
        system_template=system_template,
        user_template=user_template,
        output_field=_require_text(task, "output_field"),
        generation=generation,
        evaluation=_build_evaluation(task.get("evaluation"), generation.scheme),
        num_solutions=_positive_int(
            task.get("num_solutions", DEFAULT_SOLUTIONS), "num_solutions"
        ),
        icl=build_icl(task.get("icl"), user_template, config_dir),
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


def _prompt_templates(prompt, label: str) -> tuple[str | None, str]:
    """Pull the system (optional) and user (required) templates out of `prompt`."""
    if not isinstance(prompt, dict) or not isinstance(prompt.get("user"), str):
        raise ConfigError(f"{label} must be a mapping with a 'user' template")
    system = prompt.get("system")
    if system is not None and not isinstance(system, str):
        raise ConfigError(f"{label}.system must be a string")
    return system, prompt["user"]


def _build_generation(raw) -> GenerationConfig:
    """Validate generation settings and resolve the scheme's temperature rule."""
    generation = raw if isinstance(raw, dict) else {}
    scheme = generation.get("scheme", "greedy")
    if scheme not in SCHEMES:
        raise ConfigError(
            f"generation.scheme must be one of {', '.join(SCHEMES)}, got {scheme!r}"
        )

    return GenerationConfig(
        scheme=scheme,
        temperature=_scheme_temperature(scheme, generation.get("temperature")),
        max_tokens=_positive_int(
            generation.get("max_tokens", DEFAULT_MAX_TOKENS), "generation.max_tokens"
        ),
        n=_positive_int(generation.get("n", 1), "generation.n"),
        max_attempts=_optional_positive_int(
            generation.get("max_attempts"), "generation.max_attempts"
        ),
    )


def _optional_positive_int(value, name: str) -> int | None:
    return None if value is None else _positive_int(value, name)


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

    answer_field = raw.get("answer_field")
    if eval_type in ANSWER_FIELD_TYPES and not isinstance(answer_field, str):
        raise ConfigError(f"evaluation.answer_field is required for type {eval_type!r}")

    return EvaluationConfig(
        type=eval_type,
        answer_field=answer_field,
        extract=_extract_method(raw.get("extract"), eval_type),
        pattern=_compiled_pattern(raw.get("pattern")) if eval_type == "regex" else None,
        script=_build_script(raw) if eval_type == "script" else None,
        judge=_build_judge(raw) if eval_type == "llm_judge" else None,
    )


def _extract_method(extract, eval_type: str) -> str:
    """The configured extract method; judges default to reading a number."""
    if extract is None:
        return JUDGE_EXTRACT if eval_type == "llm_judge" else DEFAULT_EXTRACT
    if extract not in EXTRACT_METHODS:
        raise ConfigError(
            f"evaluation.extract must be one of {', '.join(EXTRACT_METHODS)}, "
            f"got {extract!r}"
        )
    return extract


def _compiled_pattern(pattern) -> str:
    if not isinstance(pattern, str):
        raise ConfigError("evaluation.pattern is required for type 'regex'")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"evaluation.pattern is not a valid regex: {exc}") from exc
    return pattern


def _build_script(raw: dict) -> ScriptConfig:
    command = raw.get("command_template")
    if not isinstance(command, str) or not command:
        raise ConfigError("evaluation.command_template is required for type 'script'")

    exit_code = raw.get("success_exit_code", 0)
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise ConfigError(
            f"evaluation.success_exit_code must be an integer, got {exit_code!r}"
        )
    return ScriptConfig(command_template=command, success_exit_code=exit_code)


def _build_judge(raw: dict) -> JudgeConfig:
    system, user = _prompt_templates(
        raw.get("judge_prompt"), "evaluation.judge_prompt"
    )
    threshold = raw.get("threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise ConfigError(
            "evaluation.threshold is required for type 'llm_judge' and must be a number"
        )

    model = raw.get("model")
    if model is not None and not isinstance(model, str):
        raise ConfigError("evaluation.model must be a string")
    return JudgeConfig(
        system_template=system, user_template=user, threshold=threshold, model=model
    )


def _is_judge(evaluation) -> bool:
    return isinstance(evaluation, dict) and evaluation.get("type") == "llm_judge"
