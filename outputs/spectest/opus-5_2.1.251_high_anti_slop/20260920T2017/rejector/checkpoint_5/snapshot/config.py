"""Loading and validation of the YAML task configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from errors import ConfigError
from icl import DEFAULT_STRATEGY, STRATEGIES, IclConfig, IclExample, IclSetup, load_examples
from templates import CHAT_TEMPLATES, DEFAULT_CHAT_TEMPLATE
from tools import (
    DEFAULT_TOOL_RESULT,
    HANDLER_TYPES,
    EchoHandler,
    ScriptHandler,
    StaticMapHandler,
    ToolConfig,
    ToolHandler,
)

SCHEMES = ("greedy", "sample", "rejection", "agentic")
#: Schemes that draw from the model at random, and so need a temperature above 0.
SAMPLING_SCHEMES = ("sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex", "llm_judge", "script")
EXTRACT_METHODS = ("last_number", "first_number", "last_line", "letter", "full")
API_TYPES = ("chat", "completions")

DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 512
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_API_TYPE = "chat"
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
    "rpm": ("rate_limits", "rpm"),
    "tpm": ("rate_limits", "tpm"),
    "max_concurrent": ("rate_limits", "max_concurrent"),
    "budget": ("cost", "budget"),
    "scheme": ("generation", "scheme"),
    "temperature": ("generation", "temperature"),
    "max_tokens": ("generation", "max_tokens"),
    "n": ("generation", "n"),
    "eval_model": ("evaluation", "model"),
    "num_solutions": (None, "num_solutions"),
    "icl_strategy": ("icl", "strategy"),
    "icl_k": ("icl", "k"),
    "api_type": (None, "api_type"),
    "chat_template": (None, "chat_template"),
}

#: Sections a task only has if it declares them; an override cannot conjure one.
OPTIONAL_SECTIONS = ("evaluation", "icl")


@dataclass(frozen=True)
class RateLimits:
    """The budgets one task's requests are paced against.

    Every field is optional and an unset one is not enforced: a task with no
    `rpm` sends requests as fast as its other budgets allow. `rpm` and `tpm` are
    spends per sliding minute, `max_concurrent` a cap on work in flight.
    """

    rpm: int | None = None
    tpm: int | None = None
    max_concurrent: int | None = None


@dataclass(frozen=True)
class CostConfig:
    """What a task's tokens cost, and the budget its run may spend.

    A `budget` of None lets the run go on until its rows are done.
    """

    prompt_cost_per_1k: float = 0.0
    completion_cost_per_1k: float = 0.0
    budget: float | None = None


#: Zero rates, which a task that configures no `cost` block is charged at.
NO_COST = CostConfig()


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
    `max_iterations` caps the API requests one `agentic` loop may make.
    """

    scheme: str
    temperature: float
    max_tokens: int
    n: int
    max_attempts: int
    max_iterations: int = DEFAULT_MAX_ITERATIONS


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
    """One task's settings.

    `api_type` picks the endpoint requests go to, and `chat_template` the markup
    a `completions` task renders its conversation with. `tools` is what an
    `agentic` task may call, and is empty for every other scheme.
    `output_schema` is the JSON Schema a response must satisfy, if any, and
    `cost` is None for a task that asks for no cost tracking at all.
    """

    name: str
    api_url: str
    model: str
    rate_limits: RateLimits
    prompt: PromptConfig
    generation: GenerationConfig
    evaluation: EvaluationConfig | None
    output_field: str
    num_solutions: int = DEFAULT_NUM_SOLUTIONS
    cost: CostConfig | None = None
    output_schema: dict[str, Any] | None = None
    icl: IclConfig | None = None
    api_type: str = DEFAULT_API_TYPE
    chat_template: str = DEFAULT_CHAT_TEMPLATE
    tools: tuple[ToolConfig, ...] = ()

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
    model = _require(task, "model", str, where)
    num_solutions = _optional(task, "num_solutions", int, DEFAULT_NUM_SOLUTIONS, where)
    if num_solutions < 1:
        raise ConfigError(f"{where}.num_solutions must be >= 1")
    generation = _build_generation(
        _optional(task, "generation", dict, {}, where), num_solutions, f"{where}.generation"
    )
    output_schema = _optional(task, "output_schema", dict, None, where)
    evaluation = _build_evaluation(task.get("evaluation"), model, f"{where}.evaluation")
    if generation.scheme == "rejection" and evaluation is None and output_schema is None:
        raise ConfigError(f"{where} needs an 'evaluation' or an 'output_schema' to reject on")
    return TaskConfig(
        name=name,
        api_url=_require(task, "api_url", str, where),
        model=model,
        rate_limits=_build_rate_limits(task, where),
        prompt=PromptConfig(
            system=_require(prompt, "system", str, f"{where}.prompt"),
            user=_require(prompt, "user", str, f"{where}.prompt"),
        ),
        generation=generation,
        evaluation=evaluation,
        output_field=_require(task, "output_field", str, where),
        num_solutions=num_solutions,
        cost=_build_cost(task.get("cost"), f"{where}.cost"),
        output_schema=output_schema,
        icl=_build_icl(task.get("icl"), base_dir, f"{where}.icl"),
        api_type=_one_of(task, "api_type", API_TYPES, DEFAULT_API_TYPE, where),
        chat_template=_one_of(task, "chat_template", CHAT_TEMPLATES, DEFAULT_CHAT_TEMPLATE, where),
        tools=_build_tools(task.get("tools"), f"{where}.tools"),
    )


def _build_rate_limits(task: dict[str, Any], where: str) -> RateLimits:
    """Read the task's budgets, with a task-level `rpm` as the default for its own.

    Each budget is optional, so a task may pace itself on requests, on tokens,
    on both, or on neither.
    """
    limits = _optional(task, "rate_limits", dict, {}, where)
    limits = {"rpm": task.get("rpm"), **limits}
    values = {
        key: _optional(limits, key, int, None, f"{where}.rate_limits")
        for key in ("rpm", "tpm", "max_concurrent")
    }
    for key, value in values.items():
        if value is not None and value <= 0:
            raise ConfigError(f"{where}.rate_limits.{key} must be > 0")
    return RateLimits(**values)


def _build_cost(cost: Any, where: str) -> CostConfig | None:
    """Read the task's token prices and budget; None when it tracks no cost."""
    if cost is None:
        return None
    _checked(cost, dict, where)
    budget = _optional(cost, "budget", (int, float), None, where)
    if budget is not None and budget <= 0:
        raise ConfigError(f"{where}.budget must be > 0")
    return CostConfig(
        prompt_cost_per_1k=float(_optional(cost, "prompt_cost_per_1k", (int, float), 0.0, where)),
        completion_cost_per_1k=float(
            _optional(cost, "completion_cost_per_1k", (int, float), 0.0, where)
        ),
        budget=None if budget is None else float(budget),
    )


def _build_generation(
    generation: dict[str, Any], num_solutions: int, where: str
) -> GenerationConfig:
    scheme = _one_of(generation, "scheme", SCHEMES, "greedy", where)

    temperature = float(_optional(generation, "temperature", (int, float), DEFAULT_TEMPERATURE, where))
    if scheme == "greedy":
        temperature = 0.0
    elif scheme in SAMPLING_SCHEMES and temperature <= 0:
        raise ConfigError(f"{where}.temperature must be > 0 for scheme '{scheme}'")

    n = _optional(generation, "n", int, 1, where)
    if scheme == "rejection" and n < 1:
        raise ConfigError(f"{where}.n must be >= 1 for scheme 'rejection'")

    default_budget = ATTEMPTS_PER_SOLUTION * num_solutions
    max_attempts = _optional(generation, "max_attempts", int, default_budget, where)
    if max_attempts < 1:
        raise ConfigError(f"{where}.max_attempts must be >= 1")

    max_iterations = _optional(generation, "max_iterations", int, DEFAULT_MAX_ITERATIONS, where)
    if max_iterations < 1:
        raise ConfigError(f"{where}.max_iterations must be >= 1")

    return GenerationConfig(
        scheme=scheme,
        temperature=temperature,
        max_tokens=_optional(generation, "max_tokens", int, DEFAULT_MAX_TOKENS, where),
        n=n if scheme == "rejection" else 1,
        max_attempts=max_attempts,
        max_iterations=max_iterations,
    )


def _build_tools(tools: Any, where: str) -> tuple[ToolConfig, ...]:
    """Read the tool definitions an agentic task offers the model."""
    if tools is None:
        return ()
    _checked(tools, list, where)
    return tuple(_build_tool(tool, f"{where}[{index}]") for index, tool in enumerate(tools))


def _build_tool(tool: Any, where: str) -> ToolConfig:
    _checked(tool, dict, where)
    parameters = _require(tool, "parameters", dict, where)
    handler = _require(tool, "handler", dict, where)
    return ToolConfig(
        name=_require(tool, "name", str, where),
        description=_require(tool, "description", str, where),
        parameters=parameters,
        handler=_build_handler(handler, parameters, f"{where}.handler"),
    )


def _build_handler(handler: dict[str, Any], parameters: dict[str, Any], where: str) -> ToolHandler:
    kind = _one_of(handler, "type", HANDLER_TYPES, None, where)
    return _HANDLERS[kind](handler, parameters, where)


def _echo_handler(handler: dict[str, Any], parameters: dict[str, Any], where: str) -> ToolHandler:
    return EchoHandler()


def _static_map_handler(
    handler: dict[str, Any], parameters: dict[str, Any], where: str
) -> ToolHandler:
    """The table is keyed by the tool's first required parameter."""
    required = _optional(parameters, "required", list, [], where)
    if not required:
        raise ConfigError(f"{where}: a static_map tool must declare a required parameter")
    return StaticMapHandler(
        key_field=required[0],
        mapping=_require(handler, "mapping", dict, where),
        default=_optional(handler, "default", str, DEFAULT_TOOL_RESULT, where),
    )


def _script_handler(handler: dict[str, Any], parameters: dict[str, Any], where: str) -> ToolHandler:
    return ScriptHandler(
        command=_require(handler, "command", str, where),
        arg_field=_require(handler, "arg_field", str, where),
    )


#: How each handler type reads its own configuration.
_HANDLERS = {
    "echo": _echo_handler,
    "static_map": _static_map_handler,
    "script": _script_handler,
}


def _build_icl(icl: Any, base_dir: Path, where: str) -> IclConfig | None:
    """Read the task's ICL setups, loading any that live in their own file."""
    if icl is None:
        return None
    if not isinstance(icl, dict):
        raise ConfigError(f"{where} must be a mapping")

    strategy = _one_of(icl, "strategy", STRATEGIES, DEFAULT_STRATEGY, where)
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


def _build_evaluation(evaluation: Any, model: str, where: str) -> EvaluationConfig | None:
    if evaluation is None:
        return None
    if not isinstance(evaluation, dict):
        raise ConfigError(f"{where} must be a mapping")

    kind = _one_of(evaluation, "type", EVALUATION_TYPES, None, where)
    default_extract = DEFAULT_JUDGE_EXTRACT if kind == "llm_judge" else DEFAULT_EXTRACT
    extract = _one_of(evaluation, "extract", EXTRACT_METHODS, default_extract, where)

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


def _one_of(
    mapping: dict[str, Any], key: str, allowed: tuple[str, ...], default: str | None, where: str
) -> str:
    """Read a key restricted to a fixed set of values; a None default requires it."""
    if default is None:
        value = _require(mapping, key, str, where)
    else:
        value = _optional(mapping, key, str, default, where)
    if value not in allowed:
        raise ConfigError(f"{where}.{key} must be one of {', '.join(allowed)}")
    return value


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
