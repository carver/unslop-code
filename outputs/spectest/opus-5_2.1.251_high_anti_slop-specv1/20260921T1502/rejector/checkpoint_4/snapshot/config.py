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
from icl import DEFAULT_STRATEGY, STRATEGIES, Icl, Setup, build_example, read_examples
from templates import TEMPLATES
from tools import DEFAULT_TOOL_RESULT, HANDLER_TYPES, Handler, Tool

SCHEMES = ("greedy", "sample", "rejection", "agentic")
# The schemes whose whole point is a non zero temperature.
SAMPLING_SCHEMES = ("sample", "rejection")
API_TYPES = ("chat", "completions")
LOCAL_EVALUATIONS = ("exact_match", "contains", "regex")
EVALUATION_TYPES = LOCAL_EVALUATIONS + ("script", "llm_judge")
EXTRACT_METHODS = ("last_number", "first_number", "last_line", "letter", "full")
ANSWER_FIELD_TYPES = ("exact_match", "contains")

DEFAULT_RPM = 60
DEFAULT_API_TYPE = "chat"
DEFAULT_CHAT_TEMPLATE = "chatml"
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_MAX_TOKENS = 512
DEFAULT_SCHEME = "greedy"
DEFAULT_NUM_SOLUTIONS = 1
# Rejection sampling budgets three attempts per solution unless told otherwise.
ATTEMPTS_PER_SOLUTION = 3
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
    "num_solutions": ("num_solutions",),
    "icl_strategy": ("icl", "strategy"),
    "icl_k": ("icl", "k"),
    "api_type": ("api_type",),
    "chat_template": ("chat_template",),
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
    max_attempts: int
    max_iterations: int


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
    api_type: str
    chat_template: str
    prompt: Prompt
    generation: Generation
    evaluation: Evaluation | None
    output_field: str
    icl: Icl | None
    num_solutions: int
    tools: list[Tool]

    @property
    def legacy(self) -> bool:
        """Whether the task keeps the Part 1 single solution result shape."""
        return self.num_solutions == 1 and self.icl is None


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
        return _single_suite(document["task"], overrides, selected, path.parent)
    if isinstance(document.get("tasks"), dict):
        return _multi_suite(document, overrides, selected, path.parent)
    raise UsageError(f"{path}: expected a top level 'task' or 'tasks' mapping")


def _single_suite(
    task: dict, overrides: dict[str, Any], selected: Sequence[str], directory: Path
) -> Suite:
    merged = _merge_overrides(task, overrides, "task")
    name = str(_require(merged, "name", "task"))
    _select([name], selected)
    return Suite([_build_task(merged, name, "task", directory)], multi=False)


def _multi_suite(
    document: dict, overrides: dict[str, Any], selected: Sequence[str], directory: Path
) -> Suite:
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
        configs.append(_build_task(merged, name, where, directory))
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


def _build_task(task: dict, name: str, where: str, directory: Path) -> TaskConfig:
    """Build one task. `directory` holds the config file, which ICL file paths are relative to."""
    model = str(_require(task, "model", where))
    num_solutions = _number(
        task.get("num_solutions", DEFAULT_NUM_SOLUTIONS), f"{where}.num_solutions", int, minimum=1
    )
    config = TaskConfig(
        name=name,
        api_url=str(_require(task, "api_url", where)).rstrip("/"),
        model=model,
        rpm=_number(task.get("rpm", DEFAULT_RPM), f"{where}.rpm", int, minimum=1),
        api_type=_choice(task.get("api_type", DEFAULT_API_TYPE), API_TYPES, f"{where}.api_type"),
        chat_template=_choice(
            task.get("chat_template", DEFAULT_CHAT_TEMPLATE), tuple(TEMPLATES), f"{where}.chat_template"
        ),
        prompt=_build_prompt(_mapping(task, "prompt", f"{where}.prompt"), f"{where}.prompt"),
        generation=_build_generation(
            _mapping(task, "generation", f"{where}.generation"),
            f"{where}.generation",
            num_solutions,
        ),
        evaluation=_build_evaluation(task.get("evaluation"), f"{where}.evaluation", model),
        output_field=str(_require(task, "output_field", where)),
        icl=_build_icl(task.get("icl"), f"{where}.icl", directory),
        num_solutions=num_solutions,
        tools=_build_tools(task.get("tools"), f"{where}.tools"),
    )
    _validate(config, where)
    return config


def _build_prompt(section: dict, where: str) -> Prompt:
    system = section.get("system")
    return Prompt(
        system=None if system is None else str(system),
        user=str(_require(section, "user", where)),
    )


def _build_generation(section: dict, where: str, num_solutions: int) -> Generation:
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
        max_attempts=_number(
            section.get("max_attempts", ATTEMPTS_PER_SOLUTION * num_solutions),
            f"{where}.max_attempts",
            int,
            minimum=1,
        ),
        max_iterations=_number(
            section.get("max_iterations", DEFAULT_MAX_ITERATIONS),
            f"{where}.max_iterations",
            int,
            minimum=1,
        ),
    )


def _build_icl(section: Any, where: str, directory: Path) -> Icl | None:
    """Build the task's ICL setups, or None when it declares none."""
    if section is None:
        return None
    if not isinstance(section, dict):
        raise UsageError(f"{where} must be a mapping")

    specs = section.get("setups") or []
    if not isinstance(specs, list):
        raise UsageError(f"{where}.setups must be a list")
    if not specs:
        return None

    limit = section.get("k")
    if limit is not None:
        limit = _number(limit, f"{where}.k", int, minimum=1)
    strategy = _choice(section.get("strategy", DEFAULT_STRATEGY), STRATEGIES, f"{where}.strategy")
    return Icl(
        setups=[
            _build_setup(spec, f"{where}.setups[{index}]", directory, limit)
            for index, spec in enumerate(specs)
        ],
        strategy=strategy,
    )


def _build_setup(spec: Any, where: str, directory: Path, limit: int | None) -> Setup:
    """Build one named setup from its inline examples or its JSONL file, keeping the first `k`."""
    if not isinstance(spec, dict):
        raise UsageError(f"{where} must be a mapping")
    name = str(_require(spec, "name", where))
    inline, file = spec.get("examples"), spec.get("file")
    if (inline is None) == (file is None):
        raise UsageError(f"{where} needs exactly one of 'examples' or 'file'")

    if file is not None:
        examples = read_examples(directory / str(file), where)
    elif isinstance(inline, list):
        examples = [
            build_example(entry, f"{where}.examples[{index}]") for index, entry in enumerate(inline)
        ]
    else:
        raise UsageError(f"{where}.examples must be a list")

    # `k` of None slices the whole list, which is the documented default.
    return Setup(name, examples[:limit])


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


def _build_tools(section: Any, where: str) -> list[Tool]:
    """Build the tools an agentic task may call; a task without any gets none."""
    if section is None:
        return []
    if not isinstance(section, list):
        raise UsageError(f"{where} must be a list")
    return [_build_tool(spec, f"{where}[{index}]") for index, spec in enumerate(section)]


def _build_tool(spec: Any, where: str) -> Tool:
    if not isinstance(spec, dict):
        raise UsageError(f"{where} must be a mapping")
    return Tool(
        name=str(_require(spec, "name", where)),
        description=str(spec.get("description", "")),
        parameters=_mapping(spec, "parameters", f"{where}.parameters"),
        handler=_build_handler(_mapping(spec, "handler", f"{where}.handler"), f"{where}.handler"),
    )


def _build_handler(section: dict, where: str) -> Handler:
    """Build one tool's handler and check it carries what its type needs."""
    kind = _choice(_require(section, "type", where), HANDLER_TYPES, f"{where}.type")
    mapping = _mapping(section, "mapping", f"{where}.mapping")
    command = section.get("command")
    arg_field = section.get("arg_field")
    if kind == "script" and (command is None or arg_field is None):
        raise UsageError(f"{where}.command and {where}.arg_field are required for a 'script' handler")
    return Handler(
        type=kind,
        mapping={str(key): str(value) for key, value in mapping.items()},
        default=str(section.get("default", DEFAULT_TOOL_RESULT)),
        command=None if command is None else str(command),
        arg_field=None if arg_field is None else str(arg_field),
    )


def _validate(config: TaskConfig, where: str) -> None:
    """Enforce the cross field rules that the dataclasses cannot express."""
    generation, evaluation = config.generation, config.evaluation

    _choice(generation.scheme, SCHEMES, f"{where}.generation.scheme")
    if generation.scheme in SAMPLING_SCHEMES and generation.temperature <= 0:
        raise UsageError(
            f"{where}.generation.temperature must be > 0 for the '{generation.scheme}' scheme"
        )
    if generation.scheme == "rejection" and evaluation is None:
        raise UsageError(f"{where}.evaluation is required for the 'rejection' scheme")

    if evaluation is not None:
        _validate_evaluation(evaluation, f"{where}.evaluation")


def _validate_evaluation(evaluation: Evaluation, where: str) -> None:
    _choice(evaluation.type, EVALUATION_TYPES, f"{where}.type")
    _choice(evaluation.extract, EXTRACT_METHODS, f"{where}.extract")
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


def _choice(value: Any, allowed: tuple[str, ...], where: str) -> str:
    """Check a value against the names the field accepts."""
    if value not in allowed:
        raise UsageError(f"{where} must be one of {', '.join(allowed)}; got '{value}'")
    return str(value)


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
