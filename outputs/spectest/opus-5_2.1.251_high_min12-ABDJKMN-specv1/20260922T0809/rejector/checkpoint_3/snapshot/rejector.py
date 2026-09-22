#!/usr/bin/env python3
"""rejector - run YAML-configured generation tasks against an OpenAI-compatible
chat completions API and write one JSONL result per input row.

Usage:
    python rejector.py run --config <path> --input <path> --output <path>
    python rejector.py run --config <multi> --input <task>=<path> --output <dir>
    python rejector.py run --config <multi> --input-dir <dir> --output <dir>
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import random
import re
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import yaml

try:
    import aiohttp
except ImportError:  # pragma: no cover - dependency is declared in requirements
    aiohttp = None


EXIT_OK = 0
EXIT_ERROR = 1

SCHEMES = ("greedy", "sample", "rejection")
ICL_STRATEGIES = ("fixed", "random", "round_robin")
EVAL_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")

# Evaluation types that compare the response against a row field.
ANSWER_FIELD_TYPES = ("exact_match", "contains")

RESPONSE_PLACEHOLDER = "__response__"
SCRIPT_TIMEOUT_SECONDS = 10.0

MAX_REQUESTS_PER_CALL = 3        # 1 initial attempt + 2 retries
RETRY_BACKOFF_SECONDS = 0.05
MAX_IN_FLIGHT = 256

# `{field}` placeholders; anything else in braces is left alone (AMBIGUITIES T16).
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
# An answer choice is an A-D that is not part of a longer word (T21).
LETTER_RE = re.compile(r"(?<![A-Za-z])([A-D])(?![A-Za-z])")


class UserError(Exception):
    """A configuration or input error: reported on stderr, exit code 1."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class Evaluation:
    type: str
    answer_field: str | None = None
    extract: str = "full"
    pattern: str | None = None
    # `script`
    command_template: str | None = None
    success_exit_code: int = 0
    # `llm_judge`
    judge_system: str | None = None
    judge_user: str | None = None
    threshold: float | None = None
    model: str | None = None


@dataclass
class IclExample:
    """One in-context example: a row-shaped input and a verbatim reply."""
    input: dict
    output: str


@dataclass
class IclSetup:
    name: str
    examples: list[IclExample]


@dataclass
class IclConfig:
    setups: list[IclSetup]
    strategy: str = "fixed"
    k: int | None = None            # None means "all examples" (spec default)

    def shots(self, setup: IclSetup) -> list[IclExample]:
        """The examples to insert for `setup`: the first `k` of them (T43)."""
        if self.k is None:
            return setup.examples
        return setup.examples[:max(0, self.k)]


@dataclass
class TaskConfig:
    name: str
    api_url: str
    model: str
    rpm: int
    system_template: str | None
    user_template: str
    scheme: str
    temperature: float
    max_tokens: int
    n: int
    evaluation: Evaluation | None
    output_field: str
    icl: IclConfig | None = None
    num_solutions: int = 1
    max_attempts: int | None = None

    @property
    def uses_list_format(self) -> bool:
        """Part 3 rows: a list of solutions, list `meta`, counting `result`."""
        return self.icl is not None or self.num_solutions > 1

    @property
    def endpoint(self) -> str:
        return self.api_url.rstrip("/") + "/v1/chat/completions"

    @property
    def concurrency(self) -> int:
        # `rpm` is the server's approximate capacity, not a client budget
        # (AMBIGUITIES T14): keep roughly that many requests in flight.
        return max(1, min(int(self.rpm), MAX_IN_FLIGHT))


def _as_mapping(value: Any, label: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise UserError(f"config: '{label}' must be a mapping")
    return value


def _as_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UserError(f"config: '{label}' must be a number")
    return float(value)


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise UserError(f"config: '{label}' must be an integer")
    return int(value)


def load_config_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except FileNotFoundError:
        raise UserError(f"config file not found: {path}")
    except OSError as exc:
        raise UserError(f"could not read config file {path}: {exc}")
    except yaml.YAMLError as exc:
        raise UserError(f"could not parse YAML config {path}: {exc}")
    if raw is None:
        raise UserError(f"config file is empty: {path}")
    if not isinstance(raw, dict):
        raise UserError("config: top level must be a mapping with a 'task' key")
    return raw


def deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge `override` onto `base` (T20); scalars replace."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged.get(key), value) if key in merged \
                else value
        return merged
    return override


def load_task_definitions(raw: dict) -> tuple[dict[str, dict], bool]:
    """Return ({name: task mapping}, is_multi_task).

    A top-level `task` key always means the Part 1 single-task format (T41).
    """
    if "task" in raw:
        task = _as_mapping(raw["task"], "task")
        name = task.get("name", "task")
        if not isinstance(name, str) or not name:
            raise UserError("config: 'task.name' must be a non-empty string")
        return {name: task}, False

    if "tasks" not in raw:
        raise UserError("config: missing required 'task' section")

    tasks = _as_mapping(raw["tasks"], "tasks")
    if not tasks:
        raise UserError("config: 'tasks' must contain at least one task")
    defaults = _as_mapping(raw.get("defaults"), "defaults")

    resolved: dict[str, dict] = {}
    for name, task in tasks.items():
        if not isinstance(name, str) or not name:
            raise UserError("config: task names must be non-empty strings")
        merged = deep_merge(copy.deepcopy(defaults),
                            _as_mapping(task, f"tasks.{name}"))
        resolved[str(name)] = merged
    return resolved, True


def build_task_config(name: str, task: dict, args: argparse.Namespace,
                      label: str, config_dir: str = "") -> TaskConfig:
    """Merge one task mapping with CLI overrides and validate the result."""
    api_url = args.api_url if args.api_url is not None else task.get("api_url")
    if not api_url or not isinstance(api_url, str):
        raise UserError(f"config: '{label}.api_url' is required")

    model = args.model if args.model is not None else task.get("model")
    if not model or not isinstance(model, str):
        raise UserError(f"config: '{label}.model' is required")

    rpm = args.rpm if args.rpm is not None else task.get("rpm", 60)
    rpm = _as_int(rpm, f"{label}.rpm")
    if rpm < 1:
        raise UserError(f"config: '{label}.rpm' must be >= 1")

    if "prompt" not in task or task.get("prompt") is None:
        raise UserError(f"config: missing required '{label}.prompt' section")
    prompt = _as_mapping(task["prompt"], f"{label}.prompt")
    user_template = prompt.get("user")
    if not isinstance(user_template, str) or not user_template:
        raise UserError(f"config: '{label}.prompt.user' is required")
    system_template = prompt.get("system")
    if system_template is not None and not isinstance(system_template, str):
        raise UserError(f"config: '{label}.prompt.system' must be a string")

    generation = _as_mapping(task.get("generation"), f"{label}.generation")

    scheme = args.scheme if args.scheme is not None else generation.get("scheme",
                                                                        "greedy")
    if scheme not in SCHEMES:
        raise UserError(
            f"config: unknown generation scheme {scheme!r}; "
            f"expected one of {', '.join(SCHEMES)}")

    if args.temperature is not None:
        temperature = float(args.temperature)
    else:
        temperature = _as_number(generation.get("temperature", 0.0),
                                 f"{label}.generation.temperature")

    max_tokens = (args.max_tokens if args.max_tokens is not None
                  else generation.get("max_tokens", 512))
    max_tokens = _as_int(max_tokens, f"{label}.generation.max_tokens")
    if max_tokens < 1:
        raise UserError(f"config: '{label}.generation.max_tokens' must be >= 1")

    n = args.n if args.n is not None else generation.get("n", 1)
    n = _as_int(n, f"{label}.generation.n")
    if n < 1:
        raise UserError(f"config: '{label}.generation.n' must be >= 1")

    if scheme == "greedy":
        # greedy forces temperature to 0.0 (AMBIGUITIES T18).
        temperature = 0.0
    elif temperature <= 0:
        raise UserError(
            f"config: scheme {scheme!r} requires 'temperature' > 0 "
            f"(got {temperature})")

    evaluation = build_evaluation(task.get("evaluation"), label,
                                  args.eval_model)
    if scheme == "rejection" and evaluation is None:
        raise UserError(f"config: '{label}.evaluation' is required for "
                        "scheme 'rejection'")
    if evaluation is not None and evaluation.type == "llm_judge" \
            and evaluation.model is None:
        evaluation.model = model

    output_field = task.get("output_field", "output")
    if not isinstance(output_field, str) or not output_field:
        raise UserError(f"config: '{label}.output_field' must be a non-empty string")

    num_solutions = (args.num_solutions if args.num_solutions is not None
                     else task.get("num_solutions", 1))
    num_solutions = _as_int(num_solutions, f"{label}.num_solutions")
    if num_solutions < 1:
        raise UserError(f"config: '{label}.num_solutions' must be >= 1")

    max_attempts = generation.get("max_attempts")
    if max_attempts is None:
        # Rejection's attempt budget when unset (the other schemes have an
        # exact attempt count of their own, T59).
        max_attempts = 3 * num_solutions
    else:
        max_attempts = _as_int(max_attempts, f"{label}.generation.max_attempts")
        if max_attempts < 1:
            raise UserError(
                f"config: '{label}.generation.max_attempts' must be >= 1")

    icl = build_icl_config(task.get("icl"), label, config_dir, user_template,
                           args)

    return TaskConfig(
        name=name,
        api_url=api_url,
        model=model,
        rpm=rpm,
        system_template=system_template,
        user_template=user_template,
        scheme=scheme,
        temperature=temperature,
        max_tokens=max_tokens,
        n=n,
        evaluation=evaluation,
        output_field=output_field,
        icl=icl,
        num_solutions=num_solutions,
        max_attempts=max_attempts,
    )


# ---------------------------------------------------------------------------
# In-context learning setups
# ---------------------------------------------------------------------------
ICL_RECORD_SHAPE = 'expected {"input": <object>, "output": <string>}'


def build_icl_config(raw: Any, label: str, config_dir: str,
                     user_template: str,
                     args: argparse.Namespace) -> IclConfig | None:
    """Parse a task's `icl` section, loading any file-backed setups.

    Returns `None` when the task configures no usable setup (T55).
    """
    strategy_flag = getattr(args, "icl_strategy", None)
    k_flag = getattr(args, "icl_k", None)

    section = _as_mapping(raw, f"{label}.icl") if raw is not None else {}
    raw_setups = section.get("setups")
    if raw_setups is None:
        return None
    if not isinstance(raw_setups, list):
        raise UserError(f"config: '{label}.icl.setups' must be a list")

    setups = [build_icl_setup(entry, label, index, config_dir)
              for index, entry in enumerate(raw_setups)]
    if not setups:
        return None

    strategy = (strategy_flag if strategy_flag is not None
                else section.get("strategy", "fixed"))
    if strategy not in ICL_STRATEGIES:
        raise UserError(
            f"config: unknown icl strategy {strategy!r}; "
            f"expected one of {', '.join(ICL_STRATEGIES)}")

    k = k_flag if k_flag is not None else section.get("k")
    if k is not None:
        k = _as_int(k, f"{label}.icl.k")
        if k < 0:
            raise UserError(f"config: '{label}.icl.k' must be >= 0")

    # Every example is rendered with `prompt.user`, so it must carry the
    # fields that template references - check before any request goes out (T53).
    fields = [f for f in template_fields(user_template)
              if f != RESPONSE_PLACEHOLDER]
    for setup in setups:
        for index, example in enumerate(setup.examples):
            for field_name in fields:
                if field_name not in example.input:
                    raise UserError(
                        f"config: icl setup {setup.name!r} example {index}: "
                        f"missing field {field_name!r} referenced by the "
                        f"prompt template")

    return IclConfig(setups=setups, strategy=strategy, k=k)


def build_icl_setup(entry: Any, label: str, index: int,
                    config_dir: str) -> IclSetup:
    setup = _as_mapping(entry, f"{label}.icl.setups[{index}]")
    name = setup.get("name")
    if not isinstance(name, str) or not name:
        raise UserError(
            f"config: '{label}.icl.setups[{index}].name' is required")

    has_examples = setup.get("examples") is not None
    has_file = setup.get("file") is not None
    if has_examples == has_file:
        raise UserError(
            f"config: icl setup {name!r} needs exactly one of 'examples' or "
            f"'file'")

    if has_file:
        path = setup["file"]
        if not isinstance(path, str) or not path:
            raise UserError(
                f"config: icl setup {name!r}: 'file' must be a path string")
        # Relative to the config file's directory, not the process cwd.
        if not os.path.isabs(path):
            path = os.path.join(config_dir, path)
        return IclSetup(name=name, examples=load_icl_file(path, name))

    raw_examples = setup["examples"]
    if not isinstance(raw_examples, list):
        raise UserError(
            f"config: icl setup {name!r}: 'examples' must be a list")
    examples = [
        parse_icl_record(record,
                         f"config: icl setup {name!r} example {position}",
                         json_wording=False)
        for position, record in enumerate(raw_examples)]
    return IclSetup(name=name, examples=examples)


def load_icl_file(path: str, setup_name: str) -> list[IclExample]:
    """Read a JSONL example file; any bad line terminates the run (exit 1)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise UserError(f"icl setup {setup_name!r}: file not found: {path}")
    except OSError as exc:
        raise UserError(
            f"icl setup {setup_name!r}: could not read {path}: {exc}")

    examples: list[IclExample] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue                      # "each non-empty line"
        where = f"icl setup {setup_name!r}: {path} line {lineno}"
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UserError(f"{where}: not valid JSON: {exc}")
        examples.append(parse_icl_record(record, where))
    return examples


def parse_icl_record(record: Any, where: str,
                     json_wording: bool = True) -> IclExample:
    """Validate one `{"input": <object>, "output": <string>}` record (T52)."""
    message = (f"{where}: not valid JSON example: {ICL_RECORD_SHAPE}"
               if json_wording else f"{where}: {ICL_RECORD_SHAPE}")
    if not isinstance(record, dict):
        raise UserError(message)
    if "input" not in record or "output" not in record:
        raise UserError(message)
    if not isinstance(record["input"], dict) \
            or not isinstance(record["output"], str):
        raise UserError(message)
    return IclExample(input=record["input"], output=record["output"])


def build_evaluation(raw: Any, label: str = "task",
                     eval_model: str | None = None) -> Evaluation | None:
    if raw is None:
        return None
    section = _as_mapping(raw, f"{label}.evaluation")
    if not section:
        return None
    etype = section.get("type")
    if etype not in EVAL_TYPES:
        raise UserError(
            f"config: unknown evaluation type {etype!r}; "
            f"expected one of {', '.join(EVAL_TYPES)}")

    extract = section.get("extract", "full")
    if extract is None:
        extract = "full"
    if extract not in EXTRACT_METHODS:
        raise UserError(
            f"config: unknown extract method {extract!r}; "
            f"expected one of {', '.join(EXTRACT_METHODS)}")

    answer_field = section.get("answer_field")
    pattern = section.get("pattern")

    if etype in ANSWER_FIELD_TYPES:
        if not answer_field or not isinstance(answer_field, str):
            raise UserError(
                f"config: evaluation type {etype!r} requires 'answer_field'")
    if etype == "regex":
        if not pattern or not isinstance(pattern, str):
            raise UserError("config: evaluation type 'regex' requires 'pattern'")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise UserError(f"config: invalid regex 'pattern': {exc}")

    evaluation = Evaluation(type=etype, answer_field=answer_field,
                            extract=extract, pattern=pattern)

    if etype == "script":
        command_template = section.get("command_template")
        if not command_template or not isinstance(command_template, str):
            raise UserError("config: evaluation type 'script' requires "
                            "'command_template'")
        evaluation.command_template = command_template
        evaluation.success_exit_code = _as_int(
            section.get("success_exit_code", 0),
            f"{label}.evaluation.success_exit_code")

    if etype == "llm_judge":
        judge = section.get("judge_prompt")
        if judge is None:
            raise UserError("config: evaluation type 'llm_judge' requires "
                            "'judge_prompt'")
        judge = _as_mapping(judge, f"{label}.evaluation.judge_prompt")
        judge_user = judge.get("user")
        if not isinstance(judge_user, str) or not judge_user:
            raise UserError(f"config: '{label}.evaluation.judge_prompt.user' "
                            "is required")
        judge_system = judge.get("system")
        if judge_system is not None and not isinstance(judge_system, str):
            raise UserError(f"config: '{label}.evaluation.judge_prompt.system' "
                            "must be a string")
        if "threshold" not in section or section.get("threshold") is None:
            raise UserError("config: evaluation type 'llm_judge' requires "
                            "'threshold'")
        evaluation.judge_system = judge_system
        evaluation.judge_user = judge_user
        evaluation.threshold = _as_number(section["threshold"],
                                          f"{label}.evaluation.threshold")
        # `--eval-model` beats `evaluation.model`, which beats the task model
        # (T35); the task model is filled in by the caller.
        model = eval_model if eval_model is not None else section.get("model")
        if model is not None and (not isinstance(model, str) or not model):
            raise UserError(f"config: '{label}.evaluation.model' must be a "
                            "non-empty string")
        evaluation.model = model

    return evaluation


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
def load_rows(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise UserError(f"input file not found: {path}")
    except OSError as exc:
        raise UserError(f"could not read input file {path}: {exc}")

    rows: list[dict] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UserError(f"input line {lineno}: invalid JSON: {exc}")
        if not isinstance(row, dict):
            raise UserError(f"input line {lineno}: expected a JSON object")
        rows.append(row)
    return rows


def template_fields(template: str | None) -> list[str]:
    if not template:
        return []
    seen: list[str] = []
    for name in PLACEHOLDER_RE.findall(template):
        if name not in seen:
            seen.append(name)
    return seen


def render_template(template: str, row: dict) -> str:
    return PLACEHOLDER_RE.sub(lambda m: str(row[m.group(1)]), template)


def required_fields(cfg: TaskConfig) -> list[str]:
    """Row fields every input row must carry for this task (T39).

    `__response__` is supplied at runtime and is never a row field.
    """
    required: list[str] = []
    templates = [cfg.system_template, cfg.user_template]
    evaluation = cfg.evaluation
    if evaluation is not None:
        templates += [evaluation.judge_system, evaluation.judge_user,
                      evaluation.command_template]
    for template in templates:
        for name in template_fields(template):
            if name != RESPONSE_PLACEHOLDER and name not in required:
                required.append(name)
    return required


def validate_rows(cfg: TaskConfig, rows: list[dict]) -> None:
    """Fail before any request is issued (AMBIGUITIES T8)."""
    required = required_fields(cfg)

    evaluation = cfg.evaluation
    answer_field = (evaluation.answer_field
                    if evaluation and evaluation.type in ANSWER_FIELD_TYPES
                    else None)

    for index, row in enumerate(rows):
        for name in required:
            if name not in row:
                raise UserError(
                    f"input row {index}: missing field {name!r} referenced by "
                    f"the prompt template")
        if answer_field and answer_field not in row:
            raise UserError(
                f"input row {index}: missing field {answer_field!r} required by "
                f"the configured evaluation")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def extract_answer(text: str, method: str) -> str | None:
    if text is None:
        return None
    if method == "full":
        return text.strip()
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return None
    if method == "last_number":
        matches = NUMBER_RE.findall(text)
        return matches[-1] if matches else None
    if method == "first_number":
        match = NUMBER_RE.search(text)
        return match.group(0) if match else None
    if method == "letter":
        match = LETTER_RE.search(text)
        return match.group(1) if match else None
    raise UserError(f"unknown extract method {method!r}")


@dataclass
class Verdict:
    """The outcome of evaluating one generated response."""
    passed: bool
    extracted: str | None = None
    judge_score: float | None = None
    judge_meta: dict | None = None


def evaluate(cfg: TaskConfig, row: dict, text: str) -> tuple[bool, str | None]:
    """Return (passed, extracted_answer) for a response body."""
    evaluation = cfg.evaluation
    assert evaluation is not None
    extracted = extract_answer(text, evaluation.extract)

    if evaluation.type == "exact_match":
        expected = str(row.get(evaluation.answer_field, "")).strip()
        passed = extracted is not None and extracted.strip() == expected
    elif evaluation.type == "contains":
        expected = str(row.get(evaluation.answer_field, ""))
        passed = expected in text
    elif evaluation.type == "regex":
        passed = re.search(evaluation.pattern, text) is not None
    else:  # pragma: no cover - validated at config load
        raise UserError(f"unknown evaluation type {evaluation.type!r}")

    return passed, extracted


def render_command(evaluation: Evaluation, row: dict, text: str) -> str:
    """Render `command_template` against the row, then resolve `__response__`.

    Row fields are expanded first; a `{__response__}` that only appears *after*
    that expansion (because it lived inside a row field) is substituted in a
    second pass.  Substitution is textual, never shell-quoted (T28).
    """
    context = dict(row)
    context[RESPONSE_PLACEHOLDER] = text
    command = render_template(evaluation.command_template, context)
    if "{" + RESPONSE_PLACEHOLDER + "}" in command:
        command = command.replace("{" + RESPONSE_PLACEHOLDER + "}", text)
    return command


async def run_script_evaluation(evaluation: Evaluation, row: dict,
                                text: str) -> Verdict:
    """Run the rendered command in a shell; its exit code is the verdict."""
    command = render_command(evaluation, row, text)
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Own process group, so a timeout can take down the shell's
            # children too - otherwise a survivor keeps the pipes open.
            start_new_session=True)
    except OSError:
        return Verdict(passed=False)

    try:
        # stdout/stderr are captured and drained, then discarded: the spec
        # forbids putting them in the JSONL output.
        await asyncio.wait_for(process.communicate(),
                               timeout=SCRIPT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        # A timeout is simply a failed evaluation.
        _kill_process_group(process)
        try:
            await process.wait()
        except Exception:  # pragma: no cover - best-effort reaping
            pass
        return Verdict(passed=False)

    return Verdict(passed=process.returncode == evaluation.success_exit_code)


def _kill_process_group(process) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except (ProcessLookupError, OSError):
            pass


def parse_score(extracted: str | None) -> float | None:
    """Turn an extracted judge answer into a number (T25)."""
    if extracted is None:
        return None
    try:
        score = float(extracted)
    except ValueError:
        return None
    return int(score) if score.is_integer() else score


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------
@dataclass
class Stats:
    total_api_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    first_request: float | None = None
    last_response: float | None = None

    def mark_request(self, when: float) -> None:
        if self.first_request is None or when < self.first_request:
            self.first_request = when

    def mark_response(self, when: float) -> None:
        if self.last_response is None or when > self.last_response:
            self.last_response = when

    @property
    def elapsed(self) -> float:
        if self.first_request is None or self.last_response is None:
            return 0.0
        return max(0.0, self.last_response - self.first_request)


@dataclass
class Attempt:
    """One completed API call."""
    text: str
    meta: dict


@dataclass
class Solution:
    """One emitted solution and the ICL setup that produced it."""
    text: str
    setup: str | None


@dataclass
class MultiOutcome:
    """A Part 3 row: many solutions, one meta entry per completed attempt."""
    solutions: list[Solution] = field(default_factory=list)
    metas: list[dict] = field(default_factory=list)
    attempts: int = 0
    passed: int = 0


@dataclass
class RowOutcome:
    output: Any
    passed: bool | None
    extracted: str | None
    attempts: int
    metas: list[dict] = field(default_factory=list)
    judge_score: float | None = None


class ApiClient:
    def __init__(self, session, cfg: TaskConfig, stats: Stats,
                 semaphore: asyncio.Semaphore):
        self.session = session
        self.cfg = cfg
        self.stats = stats
        self.semaphore = semaphore

    def build_payload(self, row: dict, setup: IclSetup | None = None) -> dict:
        return self._payload(self.cfg.system_template, self.cfg.user_template,
                             row, self.cfg.model, self.cfg.temperature,
                             setup=setup)

    def build_judge_payload(self, row: dict, text: str) -> dict:
        """The judge request: same server, its own prompt and model (T23)."""
        evaluation = self.cfg.evaluation
        context = dict(row)
        context[RESPONSE_PLACEHOLDER] = text
        return self._payload(evaluation.judge_system, evaluation.judge_user,
                             context, evaluation.model or self.cfg.model, 0.0)

    def _payload(self, system_template: str | None, user_template: str,
                 row: dict, model: str, temperature: float,
                 setup: IclSetup | None = None) -> dict:
        messages = []
        if system_template is not None:
            messages.append({"role": "system",
                             "content": render_template(system_template, row)})
        if setup is not None and self.cfg.icl is not None:
            # Examples sit between the system message and the final user
            # message, as alternating user/assistant turns.
            for example in self.cfg.icl.shots(setup):
                messages.append(
                    {"role": "user",
                     "content": render_template(user_template, example.input)})
                messages.append({"role": "assistant",
                                 "content": example.output})
        messages.append({"role": "user",
                         "content": render_template(user_template, row)})
        return {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.cfg.max_tokens,
        }

    async def complete(self, payload: dict) -> Attempt | None:
        """One logical attempt: up to MAX_REQUESTS_PER_CALL HTTP requests."""
        for request_index in range(MAX_REQUESTS_PER_CALL):
            async with self.semaphore:
                started = time.monotonic()
                self.stats.total_api_calls += 1
                self.stats.mark_request(started)
                try:
                    async with self.session.post(self.cfg.endpoint,
                                                 json=payload) as response:
                        status = response.status
                        body = await response.read()
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    # Transport failures are retried like a 5xx (T9).
                    self.stats.mark_response(time.monotonic())
                    status, body = None, b""
                finished = time.monotonic()
                self.stats.mark_response(finished)

            if status is not None and 200 <= status < 300:
                attempt = self._parse(body, finished - started,
                                      payload.get("model", self.cfg.model))
                if attempt is not None:
                    self.stats.total_prompt_tokens += attempt.meta["prompt_tokens"] or 0
                    self.stats.total_completion_tokens += (
                        attempt.meta["completion_tokens"] or 0)
                    return attempt
                return None  # unusable 2xx body: not retryable
            if status is not None and not (500 <= status < 600):
                return None  # 4xx and friends are not retried (T9)
            if request_index < MAX_REQUESTS_PER_CALL - 1:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
        return None

    def _parse(self, body: bytes, latency: float,
               model: str) -> Attempt | None:
        try:
            data = json.loads(body.decode("utf-8"))
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError,
                UnicodeDecodeError):
            return None
        if text is None:
            text = ""
        usage = data.get("usage") or {}
        meta = {
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "latency_ms": int(round(latency * 1000)),
            "finish_reason": choice.get("finish_reason"),
        }
        return Attempt(text=str(text), meta=meta)


# ---------------------------------------------------------------------------
# Row processing
# ---------------------------------------------------------------------------
async def evaluate_attempt(client: "ApiClient", row: dict,
                           text: str) -> Verdict:
    """Evaluate one generated response, dispatching on evaluation type."""
    cfg = client.cfg
    evaluation = cfg.evaluation
    assert evaluation is not None

    if evaluation.type == "script":
        return await run_script_evaluation(evaluation, row, text)

    if evaluation.type == "llm_judge":
        judge = await client.complete(client.build_judge_payload(row, text))
        if judge is None:
            # The judge call died: no score, so the row cannot pass.
            return Verdict(passed=False)
        extracted = extract_answer(judge.text, evaluation.extract)
        score = parse_score(extracted)
        passed = score is not None and score >= evaluation.threshold
        return Verdict(passed=passed, extracted=extracted, judge_score=score,
                       judge_meta=judge.meta)

    passed, extracted = evaluate(cfg, row, text)
    return Verdict(passed=passed, extracted=extracted)


def attach_judge_meta(meta: dict, verdict: Verdict) -> dict:
    """Fold a judge call's metadata into the attempt's `meta` object (T24)."""
    if verdict.judge_meta is not None:
        meta["judge_meta"] = verdict.judge_meta
    return meta


def choose_setup(cfg: TaskConfig, index: int) -> IclSetup | None:
    """The setup for attempt `index` of a row under the configured strategy."""
    if cfg.icl is None:
        return None
    setups = cfg.icl.setups
    if cfg.icl.strategy == "random":
        return random.choice(setups)
    if cfg.icl.strategy == "round_robin":
        # The cycle restarts for every row (AMBIGUITIES T44).
        return setups[index % len(setups)]
    return setups[0]                      # "fixed"


def plan_setups(cfg: TaskConfig) -> list[IclSetup | None]:
    """The setup to use for each attempt this row may make, in order."""
    if cfg.scheme == "greedy":
        if cfg.icl is not None and cfg.num_solutions > 1:
            # Declared order, at most once per setup; deterministic, so there
            # is nothing to gain from repeating one (T47 covers the no-ICL case).
            return list(cfg.icl.setups[:cfg.num_solutions])
        return [choose_setup(cfg, 0)]
    budget = (cfg.max_attempts if cfg.scheme == "rejection"
              else cfg.num_solutions)
    return [choose_setup(cfg, index) for index in range(budget)]


async def process_multi(client: "ApiClient", row: dict) -> MultiOutcome:
    """Collect up to `num_solutions` solutions for one row (Part 3)."""
    cfg = client.cfg
    # Only rejection sampling gates emission on the evaluation result (T46).
    gated = cfg.scheme == "rejection"
    outcome = MultiOutcome()

    for setup in plan_setups(cfg):
        if len(outcome.solutions) >= cfg.num_solutions:
            break
        outcome.attempts += 1
        attempt = await client.complete(client.build_payload(row, setup))
        name = setup.name if setup is not None else None
        if attempt is None:
            # A dead attempt is counted and skipped (AMBIGUITIES T48).
            continue

        meta = dict(attempt.meta)
        meta["icl_setup"] = name
        if cfg.evaluation is None:
            meta["evaluation_passed"] = None
            outcome.metas.append(meta)
            outcome.solutions.append(Solution(attempt.text, name))
            outcome.passed += 1
            continue

        verdict = await evaluate_attempt(client, row, attempt.text)
        meta["evaluation_passed"] = bool(verdict.passed)
        outcome.metas.append(attach_judge_meta(meta, verdict))
        if verdict.passed:
            outcome.passed += 1
        if verdict.passed or not gated:
            outcome.solutions.append(Solution(attempt.text, name))

    return outcome


async def process_row(client: "ApiClient", row: dict) -> RowOutcome | MultiOutcome:
    cfg = client.cfg
    if cfg.uses_list_format:
        return await process_multi(client, row)

    payload = client.build_payload(row)

    if cfg.scheme == "rejection":
        return await process_rejection(client, row, payload)

    attempt = await client.complete(payload)
    if attempt is None:
        # Retries exhausted (or a non-retryable error): the row failed.
        return RowOutcome(output=None,
                          passed=False if cfg.evaluation else None,
                          extracted=None, attempts=1, metas=[])

    if cfg.evaluation is None:
        return RowOutcome(output=attempt.text, passed=None, extracted=None,
                          attempts=1, metas=[attempt.meta])

    verdict = await evaluate_attempt(client, row, attempt.text)
    return RowOutcome(output=attempt.text, passed=verdict.passed,
                      extracted=verdict.extracted, attempts=1,
                      metas=[attach_judge_meta(attempt.meta, verdict)],
                      judge_score=verdict.judge_score)


async def process_rejection(client: "ApiClient", row: dict,
                            payload: dict) -> RowOutcome:
    cfg = client.cfg
    metas: list[dict] = []
    for _ in range(cfg.n):
        attempt = await client.complete(payload)
        if attempt is None:
            # A dead attempt fails the whole row (AMBIGUITIES T7).
            break
        verdict = await evaluate_attempt(client, row, attempt.text)
        metas.append(attach_judge_meta(attempt.meta, verdict))
        if verdict.passed:
            return RowOutcome(output=attempt.text, passed=True,
                              extracted=verdict.extracted, attempts=len(metas),
                              metas=metas, judge_score=verdict.judge_score)
    return RowOutcome(output=None, passed=False, extracted=None,
                      attempts=max(1, len(metas)), metas=metas)


def render_multi_row(cfg: TaskConfig, row: dict,
                     outcome: MultiOutcome) -> dict:
    """The Part 3 row shape: list `output`, counting `result`, list `meta`."""
    output = [{cfg.output_field: solution.text, "icl_setup": solution.setup}
              for solution in outcome.solutions]
    return {
        "input": row,
        "output": output,
        "result": {
            "passed": outcome.passed,
            "failed": outcome.attempts - outcome.passed,
            "attempts": outcome.attempts,
        },
        "meta": outcome.metas,
    }


def render_row(cfg: TaskConfig, row: dict,
               outcome: RowOutcome | MultiOutcome) -> dict:
    if isinstance(outcome, MultiOutcome):
        return render_multi_row(cfg, row, outcome)

    if outcome.output is None:
        output = None
    else:
        output = {cfg.output_field: outcome.output}

    if len(outcome.metas) == 0:
        meta: Any = None                 # no completed API call (T1)
    elif len(outcome.metas) == 1:
        meta = outcome.metas[0]          # one-attempt row (T2)
    else:
        meta = outcome.metas

    result: dict[str, Any] = {
        "passed": outcome.passed,
        "extracted_answer": outcome.extracted,
        "attempts": outcome.attempts,
    }
    if cfg.evaluation is not None and cfg.evaluation.type == "llm_judge":
        # `judge_score` belongs to judge rows only (AMBIGUITIES T26).
        result["judge_score"] = outcome.judge_score

    return {
        "input": row,
        "output": output,
        "result": result,
        "meta": meta,
    }


async def run_rows(cfg: TaskConfig, rows: list[dict],
                   stats: Stats) -> list[dict]:
    if not rows:
        return []

    semaphore = asyncio.Semaphore(cfg.concurrency)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=600)
    connector = aiohttp.TCPConnector(limit=cfg.concurrency + 8)
    async with aiohttp.ClientSession(timeout=timeout,
                                     connector=connector) as session:
        client = ApiClient(session, cfg, stats, semaphore)
        # Tasks are created in row order and the semaphore hands out slots
        # FIFO, so requests go out in input order (AMBIGUITIES T15).
        tasks = [asyncio.ensure_future(process_row(client, row)) for row in rows]
        outcomes = await asyncio.gather(*tasks)

    return [render_row(cfg, row, outcome)
            for row, outcome in zip(rows, outcomes)]


async def run_tasks(jobs: list[tuple[TaskConfig, list[dict]]]
                    ) -> dict[str, tuple[list[dict], Stats]]:
    """Run every selected task in one event loop, concurrently (T38)."""
    stats = {cfg.name: Stats() for cfg, _ in jobs}
    coroutines = [run_rows(cfg, rows, stats[cfg.name]) for cfg, rows in jobs]
    results = await asyncio.gather(*coroutines)
    return {cfg.name: (rows, stats[cfg.name])
            for (cfg, _), rows in zip(jobs, results)}


def aggregate_stats(parts: list[Stats]) -> Stats:
    """Sum counters and span the widest first-request..last-response window."""
    total = Stats()
    for part in parts:
        total.total_api_calls += part.total_api_calls
        total.total_prompt_tokens += part.total_prompt_tokens
        total.total_completion_tokens += part.total_completion_tokens
        if part.first_request is not None:
            total.mark_request(part.first_request)
        if part.last_response is not None:
            total.mark_response(part.last_response)
    return total


def count_solutions(rows: list[dict]) -> int:
    """Total emitted solutions across rows (list rows carry several)."""
    total = 0
    for row in rows:
        output = row["output"]
        if isinstance(output, list):
            total += len(output)
        elif output is not None:
            total += 1
    return total


def count_rows(rows: list[dict]) -> tuple[int, int]:
    """(passed, failed) using the Part 1 rule; list rows count once (T49)."""
    passed = 0
    failed = 0
    for row in rows:
        if isinstance(row["output"], list):
            # Part 3 row: `result.passed` is a count of passing solutions.
            if row["result"]["passed"] >= 1:
                passed += 1
            else:
                failed += 1
            continue
        verdict = row["result"]["passed"]
        if verdict is True:
            passed += 1
        elif verdict is False or row["output"] is None:
            failed += 1
        else:
            # No evaluation configured: a successful API row counts as passed.
            passed += 1
    return passed, failed


def solution_fields(rows: list[dict]) -> dict:
    """The Part 3 per-task counters (AMBIGUITIES T50, T57)."""
    total_solutions = count_solutions(rows)
    average = round(total_solutions / len(rows), 2) if rows else 0.0
    return {"total_solutions": total_solutions,
            "avg_solutions_per_input": average}


def build_summary(rows: list[dict], stats: Stats,
                  cfg: TaskConfig | None = None) -> dict:
    passed, failed = count_rows(rows)

    elapsed = stats.elapsed
    throughput = (stats.total_api_calls / elapsed * 60) if elapsed > 0 else 0.0
    summary = {
        "total": len(rows),
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": stats.total_prompt_tokens,
        "total_completion_tokens": stats.total_completion_tokens,
        "total_api_calls": stats.total_api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }
    if cfg is not None and cfg.uses_list_format:
        # A single-task run has no `tasks` object; its per-task numbers belong
        # on the summary itself (T50).
        summary.update(solution_fields(rows))
    return summary


def build_multi_summary(results: dict[str, tuple[list[dict], Stats]],
                        order: list[str],
                        configs: dict[str, TaskConfig] | None = None) -> dict:
    """Part 1's summary over every executed task, plus a `tasks` object."""
    all_rows = [row for name in order for row in results[name][0]]
    summary = build_summary(all_rows,
                            aggregate_stats([results[n][1] for n in order]))
    tasks: dict[str, dict] = {}
    for name in order:
        rows, stats = results[name]
        passed, failed = count_rows(rows)
        # Only the four keys the spec shows (AMBIGUITIES T34).
        entry = {
            "total": len(rows),
            "passed": passed,
            "failed": failed,
            "total_api_calls": stats.total_api_calls,
        }
        cfg = (configs or {}).get(name)
        if cfg is not None and cfg.uses_list_format:
            entry.update(solution_fields(rows))
        tasks[name] = entry
    summary["tasks"] = tasks
    return summary


def prepare_output_dir(path: str) -> str:
    """`--output` must be a directory for multi-task configs (T32)."""
    if os.path.exists(path) and not os.path.isdir(path):
        raise UserError(
            f"output path is not a directory: {path}; multi-task configs "
            f"write one file per task into an output directory")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise UserError(f"could not create output directory {path}: {exc}")
    return path


def write_output(path: str, rows: list[dict]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise UserError(f"could not write output file {path}: {exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class Parser(argparse.ArgumentParser):
    """argparse, but usage errors exit 1 - the spec documents only 0 and 1."""

    def error(self, message: str):  # noqa: D102
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(
        prog="rejector.py",
        description="Run a YAML-configured generation task against an "
                    "OpenAI-compatible chat completions API.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run a task over a JSONL input file")
    run.set_defaults(command="run")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument(
        "--input", action="append", default=None, metavar="[TASK=]PATH",
        help="JSONL input file; repeat as '<task>=<path>' for multi-task "
             "configs")
    run.add_argument("--input-dir", dest="input_dir", default=None,
                     metavar="DIR",
                     help="directory holding one '<task_name>.jsonl' per task")
    run.add_argument("--output", required=True,
                     help="JSONL output file, or output directory for "
                          "multi-task configs")
    run.add_argument("--task", action="append", default=None, dest="task",
                     metavar="NAME",
                     help="run only the named task; repeatable")
    run.add_argument("--eval-model", dest="eval_model", default=None,
                     help="override the judge model for selected llm_judge "
                          "tasks")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", choices=list(SCHEMES), default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    run.add_argument("--num-solutions", dest="num_solutions", type=int,
                     default=None,
                     help="number of solutions to collect per input row")
    run.add_argument("--icl-strategy", dest="icl_strategy",
                     choices=list(ICL_STRATEGIES), default=None,
                     help="override 'icl.strategy' for selected tasks")
    run.add_argument("--icl-k", dest="icl_k", type=int, default=None,
                     help="override 'icl.k' for selected tasks")
    return parser


def split_input_spec(value: str, known: set[str]) -> tuple[str | None, str]:
    """Split `--input` into (task name or None, path).

    A value is a mapping only when the text before the first `=` names a task
    in the config; that keeps ordinary paths containing `=` working (T40).
    """
    if "=" in value:
        name, _, path = value.partition("=")
        if name in known:
            return name, path
    return None, value


def resolve_inputs(args: argparse.Namespace, names: list[str],
                   selected: list[str], is_multi: bool) -> dict[str, str]:
    """Map each selected task to its input file path."""
    known = set(names)
    inputs = list(args.input or [])
    mapping: dict[str, str] = {}

    if args.input_dir is not None:
        if inputs:
            raise UserError(
                "--input and --input-dir are alternative modes; "
                "do not combine them")
        if not os.path.isdir(args.input_dir):
            raise UserError(f"input directory not found: {args.input_dir}")
        for name in selected:
            mapping[name] = os.path.join(args.input_dir, f"{name}.jsonl")
        return mapping

    if not inputs:
        raise UserError("--input or --input-dir is required")

    if not is_multi:
        if len(inputs) > 1:
            raise UserError(
                "a single-task config takes exactly one --input")
        _, path = split_input_spec(inputs[0], known)
        return {selected[0]: path}

    for value in inputs:
        name, path = split_input_spec(value, known)
        if name is None:
            raise UserError(
                f"--input {value!r}: a multi-task config needs "
                f"'<task>=<path>'; known tasks: {', '.join(names)}")
        # Mappings for unselected tasks are simply ignored (T31).
        if name in selected:
            mapping[name] = path
    return mapping


def select_tasks(args: argparse.Namespace, names: list[str]) -> list[str]:
    wanted = args.task
    if not wanted:
        return list(names)
    known = set(names)
    for name in wanted:
        if name not in known:
            raise UserError(
                f"unknown task {name!r}; known tasks: {', '.join(names)}")
    # Keep the config's ordering, without duplicates.
    return [name for name in names if name in set(wanted)]


def command_run(args: argparse.Namespace) -> int:
    if aiohttp is None:  # pragma: no cover
        raise UserError("missing dependency 'aiohttp'; "
                        "install it with: pip install -r requirements.txt")

    definitions, is_multi = load_task_definitions(load_config_file(args.config))
    names = list(definitions)
    selected = select_tasks(args, names)
    inputs = resolve_inputs(args, names, selected, is_multi)

    # Build and validate every selected task before issuing any request (T8);
    # unselected tasks are never looked at (T30).
    config_dir = os.path.dirname(os.path.abspath(args.config))
    jobs: list[tuple[TaskConfig, list[dict]]] = []
    for name in selected:
        label = f"tasks.{name}" if is_multi else "task"
        cfg = build_task_config(name, definitions[name], args, label,
                                config_dir)
        if name not in inputs:
            raise UserError(f"task {name!r}: no input file given; pass "
                            f"--input {name}=<path> or --input-dir <dir>")
        rows = load_rows(inputs[name])
        validate_rows(cfg, rows)
        jobs.append((cfg, rows))

    if is_multi:
        output_dir = prepare_output_dir(args.output)

    results = asyncio.run(run_tasks(jobs))

    configs = {cfg.name: cfg for cfg, _ in jobs}
    if is_multi:
        for name in selected:
            write_output(os.path.join(output_dir, f"{name}.jsonl"),
                         results[name][0])
        summary = build_multi_summary(results, selected, configs)
    else:
        rows, stats = results[selected[0]]
        write_output(args.output, rows)
        summary = build_summary(rows, stats, configs.get(selected[0]))

    print(json.dumps(summary))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return command_run(args)
        parser.error(f"unknown command {args.command!r}")
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover
        print("error: interrupted", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
