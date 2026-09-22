"""Task configuration: YAML loading, defaults merging, CLI overrides, validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from rejlib.cost import CostConfig
from rejlib.errors import ConfigError
from rejlib.icl import IclConfig, load_icl
from rejlib.templates import TEMPLATE_NAMES
from rejlib.tools import ToolSpec, load_tools
from rejlib.validate import (
    choice, mapping, non_negative_number, optional_number, optional_positive_int,
    positive_int, required_text, submapping,
)

SCHEMES = ("greedy", "sample", "rejection", "agentic")
#: Schemes whose whole point is a non-deterministic draw (T53).
SAMPLING_SCHEMES = ("sample", "rejection")
EVALUATION_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACT_METHODS = ("last_number", "first_number", "last_line", "letter", "full")
API_TYPES = ("chat", "completions")
#: The endpoint each `api_type` posts to.
API_PATHS = {"chat": "/v1/chat/completions", "completions": "/v1/completions"}

DEFAULT_MAX_TOKENS = 512
DEFAULT_API_TYPE = "chat"
DEFAULT_CHAT_TEMPLATE = "chatml"
#: The iteration budget of an agentic task that does not state one (T54).
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_EXTRACT = "full"
DEFAULT_SUCCESS_EXIT_CODE = 0
DEFAULT_NUM_SOLUTIONS = 1
#: "if `max_attempts` is omitted for rejection, default it to 3 * num_solutions"
ATTEMPTS_PER_SOLUTION = 3


@dataclass(frozen=True)
class RateLimits:
    """The budgets one task's requests are paced against.

    ``None`` means the budget is not configured, and so is not enforced (T70).
    """

    rpm: int | None = None
    tpm: int | None = None
    max_concurrent: int | None = None


@dataclass(frozen=True)
class ScriptSpec:
    """The shell command a `script` evaluation runs, and the code that means pass."""

    command_template: str
    success_exit_code: int = DEFAULT_SUCCESS_EXIT_CODE


@dataclass(frozen=True)
class JudgeSpec:
    """The second model call an `llm_judge` evaluation scores a response with."""

    user_prompt: str
    threshold: float
    system_prompt: str | None = None
    #: Judge model; ``None`` means "use the task's model".
    model: str | None = None


@dataclass(frozen=True)
class Evaluation:
    """How a response is judged against its input row."""

    type: str
    answer_field: str | None = None
    extract: str = DEFAULT_EXTRACT
    pattern: str | None = None
    script: ScriptSpec | None = None
    judge: JudgeSpec | None = None


@dataclass(frozen=True)
class Generation:
    """Sampling parameters for one task."""

    scheme: str = "greedy"
    temperature: float = 0.0
    max_tokens: int = DEFAULT_MAX_TOKENS
    n: int = 1
    #: Rejection sampling's attempt budget, defaulted from ``num_solutions``.
    max_attempts: int = ATTEMPTS_PER_SOLUTION
    #: How many API requests one agentic loop may spend.
    max_iterations: int = DEFAULT_MAX_ITERATIONS


@dataclass(frozen=True)
class TaskConfig:
    """A validated task definition."""

    api_url: str
    model: str
    user_prompt: str
    output_field: str
    generation: Generation
    evaluation: Evaluation | None
    name: str | None = None
    system_prompt: str | None = None
    rate_limits: RateLimits = RateLimits()
    #: ``None`` when the task prices nothing, which keeps `cost` out of the summary.
    cost: CostConfig | None = None
    #: The JSON Schema a response must satisfy, when the task requires one.
    output_schema: dict | None = None
    icl: IclConfig | None = None
    num_solutions: int = DEFAULT_NUM_SOLUTIONS
    api_type: str = DEFAULT_API_TYPE
    chat_template: str = DEFAULT_CHAT_TEMPLATE
    #: The tools an `agentic` loop may call.
    tools: tuple[ToolSpec, ...] = ()

    @property
    def rpm(self) -> int | None:
        """The task's request budget, or ``None`` when RPM limiting is off."""
        return self.rate_limits.rpm

    @property
    def request_url(self) -> str:
        return f"{self.api_url.rstrip('/')}{API_PATHS[self.api_type]}"

    @property
    def list_format(self) -> bool:
        """Whether rows carry lists of solutions and per-attempt metadata."""
        return self.icl is not None or self.num_solutions > 1

    @property
    def rejection_attempts(self) -> int:
        """Rejection's attempt budget: Part 1's ``n`` in legacy mode (T47)."""
        return self.generation.max_attempts if self.list_format else self.generation.n


@dataclass(frozen=True)
class RunConfig:
    """Every task a run will execute, keyed by task name in config order."""

    tasks: dict[str, TaskConfig]
    #: True for a `defaults` + `tasks` config, False for the Part 1 `task` format.
    multi: bool
    #: Every task name the config file defines, selected or not.
    names: tuple[str, ...] = ()

    @property
    def only(self) -> TaskConfig:
        """The single task of a Part 1 config."""
        return next(iter(self.tasks.values()))


def load_config(path, overrides: dict | None = None, selected=None) -> RunConfig:
    """Read the YAML config at ``path``, apply CLI overrides, and validate.

    A top-level ``task`` key is the Part 1 single-task format; otherwise each
    entry of ``tasks`` is merged over ``defaults``. Tasks that ``selected``
    leaves out are neither built nor validated. Overrides with a value of
    ``None`` are treated as "not provided".
    """
    provided = {key: value for key, value in (overrides or {}).items() if value is not None}
    bodies, defaults, multi = _task_bodies(Path(path))

    tasks = {}
    for name in _select(list(bodies), selected):
        label = f"tasks.{name}" if multi else "task"
        body = _merged(defaults, mapping(bodies[name], label))
        tasks[name] = _build_task(body, provided, name, label, Path(path).parent)
    return RunConfig(tasks=tasks, multi=multi, names=tuple(bodies))


def _task_bodies(path: Path) -> tuple[dict, dict, bool]:
    """Raw task bodies, the shared defaults, and whether the config is multi-task."""
    document = _read_document(path)
    if isinstance(document.get("task"), dict):
        return {_single_task_name(document["task"]): document["task"]}, {}, False

    tasks = document.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        raise ConfigError(
            f"config {path} must contain a 'task' mapping or a non-empty 'tasks' mapping"
        )
    return tasks, submapping(document, "defaults", "defaults"), True


def _read_document(path: Path) -> dict:
    try:
        text = path.read_text()
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in config {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError(f"config {path} must be a YAML mapping")
    return document


def _single_task_name(task: dict) -> str:
    """The Part 1 task name, from ``task.name``."""
    name = task.get("name")
    return name if isinstance(name, str) and name else "task"


def _select(available: list[str], selected) -> list[str]:
    """Narrow the configured tasks to the ``--task`` selection, in config order."""
    if not selected:
        return available
    unknown = [name for name in selected if name not in available]
    if unknown:
        raise ConfigError(f"--task: config defines no task named {', '.join(unknown)}")
    return [name for name in available if name in selected]


def _merged(defaults: dict, task: dict) -> dict:
    """Task values override ``defaults``; mappings in both are merged recursively."""
    merged = dict(defaults)
    for key, value in task.items():
        shared = merged.get(key)
        if isinstance(shared, dict) and isinstance(value, dict):
            merged[key] = _merged(shared, value)
        else:
            merged[key] = value
    return merged


def _build_task(body: dict, provided: dict, name: str, label: str,
                base_dir: Path) -> TaskConfig:
    """Validate one merged task body into a ``TaskConfig``."""
    prompt = submapping(body, "prompt", f"{label}.prompt")
    num_solutions = positive_int(
        f"{label}.num_solutions",
        provided.get("num_solutions", body.get("num_solutions", DEFAULT_NUM_SOLUTIONS)),
    )
    config = TaskConfig(
        name=name,
        api_url=provided.get("api_url") or required_text(body, "api_url", f"{label}.api_url"),
        model=provided.get("model") or required_text(body, "model", f"{label}.model"),
        rate_limits=_rate_limits(body, provided, label),
        cost=_cost(body, provided, label),
        output_schema=_output_schema(body, label),
        system_prompt=prompt.get("system"),
        user_prompt=required_text(prompt, "user", f"{label}.prompt.user"),
        generation=_generation(
            submapping(body, "generation", f"{label}.generation"), provided, label,
            num_solutions,
        ),
        evaluation=_evaluation(body.get("evaluation"), provided, f"{label}.evaluation"),
        output_field=required_text(body, "output_field", f"{label}.output_field"),
        icl=load_icl(body.get("icl"), base_dir, f"{label}.icl", provided),
        num_solutions=num_solutions,
        api_type=choice(
            f"{label}.api_type",
            provided.get("api_type", body.get("api_type", DEFAULT_API_TYPE)), API_TYPES,
        ),
        chat_template=choice(
            f"{label}.chat_template",
            provided.get("chat_template", body.get("chat_template", DEFAULT_CHAT_TEMPLATE)),
            TEMPLATE_NAMES,
        ),
        tools=load_tools(body.get("tools"), f"{label}.tools"),
    )
    if (config.generation.scheme == "rejection" and config.evaluation is None
            and config.output_schema is None):
        # "rejection sampling may use `output_schema` even when no separate
        #  `evaluation` block is configured"
        raise ConfigError(
            f"{label}.evaluation or {label}.output_schema is required for scheme 'rejection'"
        )
    return config


def _rate_limits(body: dict, provided: dict, label: str) -> RateLimits:
    """The task's `rate_limits`, with the Part 1 top-level `rpm` as a fallback (T70)."""
    raw = submapping(body, "rate_limits", f"{label}.rate_limits")
    return RateLimits(
        rpm=optional_positive_int(
            f"{label}.rpm", provided.get("rpm", raw.get("rpm", body.get("rpm")))
        ),
        tpm=optional_positive_int(
            f"{label}.rate_limits.tpm", provided.get("tpm", raw.get("tpm"))
        ),
        max_concurrent=optional_positive_int(
            f"{label}.rate_limits.max_concurrent",
            provided.get("max_concurrent", raw.get("max_concurrent")),
        ),
    )


def _cost(body: dict, provided: dict, label: str) -> CostConfig | None:
    """The task's `cost` rates and budget, or ``None`` when it prices nothing (T77)."""
    raw = submapping(body, "cost", f"{label}.cost")
    budget = provided.get("budget", raw.get("budget"))
    if not raw and budget is None:
        return None
    return CostConfig(
        prompt_cost_per_1k=_rate(label, raw, "prompt_cost_per_1k"),
        completion_cost_per_1k=_rate(label, raw, "completion_cost_per_1k"),
        budget=optional_number(f"{label}.cost.budget", budget),
    )


def _rate(label: str, raw: dict, key: str) -> float:
    """One cost rate; a rate the task leaves out prices its calls at nothing."""
    value = raw.get(key)
    return 0.0 if value is None else non_negative_number(f"{label}.cost.{key}", value)


def _output_schema(body: dict, label: str) -> dict | None:
    """The task's `output_schema`, which must be a JSON Schema mapping."""
    schema = body.get("output_schema")
    return None if schema is None else mapping(schema, f"{label}.output_schema")


def _generation(raw: dict, provided: dict, label: str, num_solutions: int) -> Generation:
    """Merge config and overrides, then enforce the per-scheme temperature rules."""
    scheme = choice(f"{label}.generation.scheme",
                    provided.get("scheme", raw.get("scheme", "greedy")), SCHEMES)
    requested = provided.get("temperature", raw.get("temperature", 0.0))
    generation = Generation(
        scheme=scheme,
        temperature=0.0 if scheme == "greedy" else _temperature(requested, label),
        max_tokens=positive_int(
            f"{label}.generation.max_tokens",
            provided.get("max_tokens", raw.get("max_tokens", DEFAULT_MAX_TOKENS)),
        ),
        n=positive_int(f"{label}.generation.n", provided.get("n", raw.get("n", 1))),
        max_attempts=positive_int(
            f"{label}.generation.max_attempts",
            raw.get("max_attempts", ATTEMPTS_PER_SOLUTION * num_solutions),
        ),
        max_iterations=positive_int(
            f"{label}.generation.max_iterations",
            raw.get("max_iterations", DEFAULT_MAX_ITERATIONS),
        ),
    )
    if scheme in SAMPLING_SCHEMES and generation.temperature <= 0.0:
        raise ConfigError(f"{label}.generation.temperature must be > 0 for scheme {scheme!r}")
    return generation


def _evaluation(raw, provided: dict, label: str) -> Evaluation | None:
    """Build the evaluation, or ``None`` when the task configures none."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} must be a mapping")

    eval_type = choice(f"{label}.type", raw.get("type"), EVALUATION_TYPES)
    extract = choice(f"{label}.extract", raw.get("extract") or DEFAULT_EXTRACT,
                     EXTRACT_METHODS)

    evaluation = Evaluation(
        type=eval_type,
        answer_field=raw.get("answer_field"),
        extract=extract,
        pattern=raw.get("pattern"),
        script=_script(raw, label) if eval_type == "script" else None,
        judge=_judge(raw, provided, label) if eval_type == "llm_judge" else None,
    )
    if eval_type == "regex":
        _compiled_pattern(evaluation.pattern, label)
    elif eval_type in ("exact_match", "contains") and not evaluation.answer_field:
        raise ConfigError(f"{label}.answer_field is required for type {eval_type!r}")
    return evaluation


def _script(raw: dict, label: str) -> ScriptSpec:
    """The `script` evaluation's command and success code."""
    success = raw.get("success_exit_code", DEFAULT_SUCCESS_EXIT_CODE)
    if isinstance(success, bool) or not isinstance(success, int):
        raise ConfigError(f"{label}.success_exit_code must be an integer, got {success!r}")
    return ScriptSpec(
        command_template=required_text(raw, "command_template", f"{label}.command_template"),
        success_exit_code=success,
    )


def _judge(raw: dict, provided: dict, label: str) -> JudgeSpec:
    """The `llm_judge` evaluation's prompt, threshold, and model."""
    prompt = submapping(raw, "judge_prompt", f"{label}.judge_prompt")
    model = provided.get("eval_model") or raw.get("model")
    if model is not None and not isinstance(model, str):
        raise ConfigError(f"{label}.model must be a string, got {model!r}")
    return JudgeSpec(
        system_prompt=prompt.get("system"),
        user_prompt=required_text(prompt, "user", f"{label}.judge_prompt.user"),
        threshold=_threshold(raw.get("threshold"), label),
        model=model,
    )


def _compiled_pattern(pattern, label: str):
    if not isinstance(pattern, str) or not pattern:
        raise ConfigError(f"{label}.pattern is required for type 'regex'")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"{label}.pattern is not a valid regex: {exc}") from exc


def _temperature(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ConfigError(
            f"{label}.generation.temperature must be a non-negative number, got {value!r}"
        )
    return float(value)


def _threshold(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label}.threshold is required and must be a number, got {value!r}")
    return float(value)
