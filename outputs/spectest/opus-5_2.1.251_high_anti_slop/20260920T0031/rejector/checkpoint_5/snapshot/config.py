"""Loading and validation of the YAML configuration, single-task or multi-task."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any

import yaml

from chat_templates import DEFAULT_TEMPLATE, TEMPLATES
from cost import CostConfig
from errors import RejectorError
from evaluation import (
    ANSWER_FIELD_TYPES,
    EVALUATION_TYPES,
    EXTRACTORS,
    LLM_JUDGE,
    SCRIPT,
    EvaluationConfig,
)
from icl import FIXED, STRATEGIES, IclConfig, load_setups
from limits import DEFAULT_MAX_CONCURRENT, RateLimits
from templates import PromptConfig
from tools import Tool, load_tools

GREEDY = "greedy"
SAMPLE = "sample"
REJECTION = "rejection"
AGENTIC = "agentic"
SCHEMES = frozenset({GREEDY, SAMPLE, REJECTION, AGENTIC})
#: Schemes that draw from the model and therefore need a temperature above zero.
SAMPLING_SCHEMES = frozenset({SAMPLE, REJECTION})

CHAT = "chat"
COMPLETIONS = "completions"
API_TYPES = frozenset({CHAT, COMPLETIONS})

#: Sections of `defaults` that are merged key by key with the task's own section.
NESTED_SECTIONS = ("prompt", "generation", "evaluation", "icl", "rate_limits", "cost")

#: Rejection attempts allowed per requested solution when `max_attempts` is omitted.
DEFAULT_ATTEMPTS_PER_SOLUTION = 3

DEFAULT_MAX_TOKENS = 512
DEFAULT_EXTRACT = "full"
#: Requests one agentic loop may spend before it gives up on reaching an answer.
DEFAULT_MAX_ITERATIONS = 10


@dataclass(frozen=True)
class GenerationConfig:
    """Sampling parameters and the scheme that drives how many attempts a row gets."""

    scheme: str
    temperature: float
    max_tokens: int
    n: int
    #: Attempt ceiling of a multi-solution rejection run; unused by the other schemes.
    max_attempts: int | None = None
    #: API requests one agentic loop may spend; unused by the other schemes.
    max_iterations: int = DEFAULT_MAX_ITERATIONS

    @property
    def attempts(self) -> int:
        """Logical generation attempts per row: `n` for rejection sampling, else 1."""
        return self.n if self.scheme == REJECTION else 1


@dataclass(frozen=True)
class TaskConfig:
    """A fully validated task definition."""

    name: str
    api_url: str
    model: str
    prompt: PromptConfig
    generation: GenerationConfig
    evaluation: EvaluationConfig | None
    output_field: str
    #: Request, token and concurrency budgets this task's calls are paced by.
    limits: RateLimits = RateLimits()
    #: Token prices and run budget; None leaves the task out of cost accounting.
    cost: CostConfig | None = None
    #: JSON Schema the response must satisfy before anything else scores it.
    output_schema: dict[str, Any] | None = None
    icl: IclConfig | None = None
    num_solutions: int = 1
    api_type: str = CHAT
    #: Template folding the conversation into a prompt; only used by `completions` tasks.
    chat_template: str = DEFAULT_TEMPLATE
    #: Tools an agentic task may call; empty for every other scheme.
    tools: tuple[Tool, ...] = ()

    @property
    def multi_solution(self) -> bool:
        """Whether the task uses the multi-solution schemes and the list output format."""
        return self.num_solutions > 1 or self.icl is not None

    @property
    def agentic(self) -> bool:
        """Whether a generation attempt is a tool-calling loop rather than one request."""
        return self.generation.scheme == AGENTIC


@dataclass(frozen=True)
class TaskSuite:
    """The tasks a run will execute, plus the shape of the config they came from."""

    tasks: tuple[TaskConfig, ...]
    #: Every task name in the config, including ones `--task` left out.
    names: tuple[str, ...]
    multi: bool


def load_tasks(path: str, overrides: dict[str, Any], selected: Sequence[str] | None = None) -> TaskSuite:
    """Read the YAML config at `path`, apply CLI overrides, and validate the selected tasks."""
    document = _read_yaml(path)
    sections = _task_sections(path, document)
    multi = "task" not in document
    names = _select(sections, selected)
    config_dir = os.path.dirname(os.path.abspath(path))
    return TaskSuite(
        tasks=tuple(
            _build_task(name, sections[name], overrides, config_dir, f"tasks.{name}" if multi else "task")
            for name in names
        ),
        names=tuple(sections),
        multi=multi,
    )


def _read_yaml(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise RejectorError(f"{path}: expected a YAML mapping at the top level")
    return document


def _task_sections(path: str, document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """One merged config section per task name, in the order the config lists them."""
    single = document.get("task")
    if isinstance(single, dict):
        return {str(single.get("name", "task")): single}

    tasks = document.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        raise RejectorError(f"{path}: config must contain a 'task' mapping or a non-empty 'tasks' mapping")

    defaults = document.get("defaults") or {}
    return {str(name): _with_defaults(defaults, name, section) for name, section in tasks.items()}


def _with_defaults(defaults: dict[str, Any], name: str, section: Any) -> dict[str, Any]:
    """Task values layered over `defaults`, merging the nested sections key by key."""
    if not isinstance(section, dict):
        raise RejectorError(f"tasks.{name} must be a mapping")

    merged = {**defaults, **section}
    for key in NESTED_SECTIONS:
        nested = {**(defaults.get(key) or {}), **(section.get(key) or {})}
        if nested:
            merged[key] = nested
    return merged


def _select(sections: dict[str, dict[str, Any]], selected: Sequence[str] | None) -> list[str]:
    """The task names to run; `--task` narrows them and unknown names are an error."""
    if not selected:
        return list(sections)
    wanted = set(selected)
    unknown = sorted(wanted - set(sections))
    if unknown:
        raise RejectorError(f"--task names unknown task(s): {', '.join(unknown)}")
    return [name for name in sections if name in wanted]


def _build_task(
    name: str, section: dict[str, Any], overrides: dict[str, Any], config_dir: str, prefix: str
) -> TaskConfig:
    """Validate one task section; `prefix` names it in error messages."""
    values = _merged(section, overrides, ("api_url", "model", "num_solutions", "api_type", "chat_template"))
    model = _text(values, "model", prefix)
    num_solutions = _positive(values.get("num_solutions"), "num_solutions", prefix) or 1
    generation = _build_generation(
        _merged(section.get("generation"), overrides, ("scheme", "temperature", "max_tokens", "n")),
        num_solutions,
        prefix,
    )
    output_schema = _build_schema(section.get("output_schema"), prefix)
    return TaskConfig(
        name=name,
        api_url=_text(values, "api_url", prefix).rstrip("/"),
        model=model,
        prompt=_build_prompt(section.get("prompt"), f"{prefix}.prompt"),
        generation=generation,
        evaluation=_build_evaluation(
            section.get("evaluation"), generation.scheme, model, overrides, prefix, output_schema
        ),
        output_field=_text(values, "output_field", prefix),
        limits=_build_limits(
            _merged(section.get("rate_limits"), overrides, ("rpm", "tpm", "max_concurrent")),
            section.get("rpm"),
            prefix,
        ),
        cost=_build_cost(_merged(section.get("cost"), overrides, ("budget",)), prefix),
        output_schema=output_schema,
        icl=_build_icl(section.get("icl"), config_dir, overrides, prefix),
        num_solutions=num_solutions,
        api_type=_choice(values.get("api_type", CHAT), API_TYPES, "api_type", prefix),
        chat_template=_choice(values.get("chat_template", DEFAULT_TEMPLATE), TEMPLATES, "chat_template", prefix),
        tools=_build_tools(section.get("tools"), generation.scheme, f"{prefix}.tools"),
    )


def _build_limits(values: dict[str, Any], task_rpm: Any, prefix: str) -> RateLimits:
    """The task's rate limits, still accepting `rpm` spelled as a task-level key.

    Omitting `rpm` leaves request pacing off, and `max_concurrent` then falls
    back to a minute of the request budget, or to a small default without one.
    """
    prefix = f"{prefix}.rate_limits"
    rpm = _positive(values.get("rpm", task_rpm), "rpm", prefix)
    concurrent = _positive(values.get("max_concurrent"), "max_concurrent", prefix)
    return RateLimits(
        rpm=rpm,
        tpm=_positive(values.get("tpm"), "tpm", prefix),
        max_concurrent=concurrent or rpm or DEFAULT_MAX_CONCURRENT,
    )


def _build_cost(values: dict[str, Any], prefix: str) -> CostConfig | None:
    """Token prices and the run budget; an absent section leaves the task uncosted."""
    if not values:
        return None
    prefix = f"{prefix}.cost"
    budget = values.get("budget")
    return CostConfig(
        prompt_per_1k=_number(values.get("prompt_cost_per_1k", 0.0), "prompt_cost_per_1k", float, prefix),
        completion_per_1k=_number(values.get("completion_cost_per_1k", 0.0), "completion_cost_per_1k", float, prefix),
        budget=None if budget is None else _number(budget, "budget", float, prefix),
    )


def _build_schema(section: Any, prefix: str) -> dict[str, Any] | None:
    """A task's `output_schema`, kept as the JSON Schema document it already is."""
    if section is None:
        return None
    if not isinstance(section, dict):
        raise RejectorError(f"{prefix}.output_schema must be a mapping")
    return section


def _choice(value: Any, allowed: Collection[str], key: str, prefix: str) -> str:
    """One of a fixed set of names, reported with the set when it is not."""
    text = str(value)
    if text not in allowed:
        raise RejectorError(f"{prefix}.{key} must be one of {sorted(allowed)}, got {text!r}")
    return text


def _build_tools(section: Any, scheme: str, prefix: str) -> tuple[Tool, ...]:
    """A task's tool definitions; agentic generation needs at least one, the other schemes none."""
    if section is None:
        if scheme == AGENTIC:
            raise RejectorError(f"{prefix} is required for scheme '{AGENTIC}'")
        return ()
    return load_tools(section, prefix)


def _merged(section: Any, overrides: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Config section with the CLI overrides that apply to it layered on top."""
    values = dict(section or {})
    values.update({key: overrides[key] for key in keys if overrides.get(key) is not None})
    return values


def _text(values: dict[str, Any], key: str, prefix: str) -> str:
    value = values.get(key)
    if not value:
        raise RejectorError(f"{prefix}.{key} is required")
    return str(value)


def _number(value: Any, key: str, cast: Callable[[Any], Any], prefix: str) -> Any:
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise RejectorError(f"{prefix}.{key} must be a number, got {value!r}") from None


def _positive(value: Any, key: str, prefix: str) -> int | None:
    """A whole number of one or more, or None when the setting was left out."""
    if value is None:
        return None
    number = _number(value, key, int, prefix)
    if number < 1:
        raise RejectorError(f"{prefix}.{key} must be >= 1, got {number}")
    return number


def _build_prompt(section: Any, prefix: str) -> PromptConfig:
    if not isinstance(section, dict) or not section.get("user"):
        raise RejectorError(f"{prefix}.user is required")
    return PromptConfig(system=str(section.get("system", "")), user=str(section["user"]))


def _build_generation(values: dict[str, Any], num_solutions: int, prefix: str) -> GenerationConfig:
    prefix = f"{prefix}.generation"
    scheme = str(values.get("scheme", "greedy"))
    if scheme not in SCHEMES:
        raise RejectorError(f"{prefix}.scheme must be one of {sorted(SCHEMES)}, got {scheme!r}")

    temperature = _number(values.get("temperature", 0.0), "temperature", float, prefix)
    if scheme == GREEDY:
        temperature = 0.0
    elif scheme in SAMPLING_SCHEMES and temperature <= 0:
        raise RejectorError(f"{prefix}.temperature must be > 0 for scheme '{scheme}', got {temperature}")

    n = _number(values.get("n", 1), "n", int, prefix)
    if n < 1:
        raise RejectorError(f"{prefix}.n must be >= 1, got {n}")

    max_attempts = _positive(values.get("max_attempts"), "max_attempts", prefix)
    if scheme == REJECTION and max_attempts is None:
        max_attempts = DEFAULT_ATTEMPTS_PER_SOLUTION * num_solutions

    return GenerationConfig(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_number(values.get("max_tokens", DEFAULT_MAX_TOKENS), "max_tokens", int, prefix),
        n=n,
        max_attempts=max_attempts,
        max_iterations=_positive(values.get("max_iterations"), "max_iterations", prefix) or DEFAULT_MAX_ITERATIONS,
    )


def _build_icl(section: Any, config_dir: str, overrides: dict[str, Any], prefix: str) -> IclConfig | None:
    """Validate a task's `icl` section; absent means the task prompts without demonstrations."""
    if section is None:
        return None
    prefix = f"{prefix}.icl"
    if not isinstance(section, dict):
        raise RejectorError(f"{prefix} must be a mapping")

    strategy = str(overrides.get("icl_strategy") or section.get("strategy", FIXED))
    if strategy not in STRATEGIES:
        raise RejectorError(f"{prefix}.strategy must be one of {list(STRATEGIES)}, got {strategy!r}")

    return IclConfig(
        setups=load_setups(section.get("setups"), config_dir, prefix),
        strategy=strategy,
        k=_positive(overrides.get("icl_k") or section.get("k"), "k", prefix),
    )


def _build_evaluation(
    section: Any, scheme: str, model: str, overrides: dict[str, Any], prefix: str, output_schema: Any = None
) -> EvaluationConfig | None:
    """The task's evaluation; rejection sampling needs one unless a schema gates it instead."""
    prefix = f"{prefix}.evaluation"
    if section is None:
        if scheme == REJECTION and output_schema is None:
            raise RejectorError(f"{prefix} is required for scheme '{REJECTION}'")
        return None
    if not isinstance(section, dict):
        raise RejectorError(f"{prefix} must be a mapping")

    eval_type = section.get("type")
    if eval_type not in EVALUATION_TYPES:
        raise RejectorError(f"{prefix}.type must be one of {sorted(EVALUATION_TYPES)}, got {eval_type!r}")

    extract = str(section.get("extract", DEFAULT_EXTRACT))
    if extract not in EXTRACTORS:
        raise RejectorError(f"{prefix}.extract must be one of {sorted(EXTRACTORS)}, got {extract!r}")

    answer_field = section.get("answer_field")
    if eval_type in ANSWER_FIELD_TYPES and not answer_field:
        raise RejectorError(f"{prefix}.answer_field is required for type '{eval_type}'")

    return EvaluationConfig(
        type=eval_type,
        extract=extract,
        answer_field=str(answer_field) if answer_field else None,
        **_type_fields(eval_type, section, model, overrides, prefix),
    )


def _type_fields(
    eval_type: str, section: dict[str, Any], model: str, overrides: dict[str, Any], prefix: str
) -> dict[str, Any]:
    """The configuration fields that belong to one evaluation type only."""
    if eval_type == "regex":
        return {"pattern": _compile_pattern(section.get("pattern"), prefix)}
    if eval_type == SCRIPT:
        return {
            "command_template": _text(section, "command_template", prefix),
            "success_exit_code": _number(section.get("success_exit_code", 0), "success_exit_code", int, prefix),
        }
    if eval_type == LLM_JUDGE:
        return _judge_fields(section, model, overrides, prefix)
    return {}


def _judge_fields(section: dict[str, Any], model: str, overrides: dict[str, Any], prefix: str) -> dict[str, Any]:
    """Judge prompt, pass threshold and the model the judge call is sent to."""
    if section.get("threshold") is None:
        raise RejectorError(f"{prefix}.threshold is required for type '{LLM_JUDGE}'")
    return {
        "judge_prompt": _build_prompt(section.get("judge_prompt"), f"{prefix}.judge_prompt"),
        "threshold": _number(section.get("threshold"), "threshold", float, prefix),
        "model": str(overrides.get("eval_model") or section.get("model") or model),
    }


def _compile_pattern(pattern: Any, prefix: str) -> re.Pattern[str]:
    if not pattern:
        raise RejectorError(f"{prefix}.pattern is required for type 'regex'")
    try:
        return re.compile(str(pattern))
    except re.error as exc:
        raise RejectorError(f"{prefix}.pattern is not a valid regex: {exc}") from None
