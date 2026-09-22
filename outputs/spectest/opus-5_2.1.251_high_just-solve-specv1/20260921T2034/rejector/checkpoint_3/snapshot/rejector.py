#!/usr/bin/env python3
"""rejector - run YAML-configured prompt tasks against an OpenAI-compatible API.

Usage:
    python rejector.py run --config <path> --input <path> --output <path> [options]
    python rejector.py run --config <multi.yaml> --input <task>=<path> ... --output <dir>
    python rejector.py run --config <multi.yaml> --input-dir <dir> --output <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import os
import random
import re
import signal
import sys
import time
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import aiohttp
import yaml

EXIT_OK = 0
EXIT_ERROR = 1

SCHEMES = ("greedy", "sample", "rejection")
ICL_STRATEGIES = ("fixed", "random", "round_robin")
EVAL_TYPES = ("exact_match", "contains", "regex", "llm_judge", "script")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")

MAX_HTTP_TRIES = 3  # total requests per logical attempt, including the first

SCRIPT_TIMEOUT = 10.0  # seconds; a timeout is a failed evaluation
RESPONSE_KEY = "__response__"
RESPONSE_PLACEHOLDER = "{%s}" % RESPONSE_KEY

# Placeholder such as {question}. Deliberately narrow so that JSON braces or
# prose inside a prompt template are left untouched.
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Integers/decimals, preferring a comma-grouped form when one is present.
NUMBER_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?|-?\.\d+")

# Multiple-choice letters, most explicit form first.
LETTER_RES = [
    re.compile(
        r"(?i:answer|choice|option|letter)\b(?:\s+(?i:is|would\s+be))?"
        r"\s*[:=\-]?\s*[\(\[]?\s*([A-D])(?![A-Za-z0-9])"
    ),
    re.compile(r"[\(\[]\s*([A-D])\s*[\)\]]"),
    re.compile(r"(?<![A-Za-z0-9])([A-D])\s*[\)\].:,]"),
    re.compile(r"(?<![A-Za-z0-9])([A-D])(?![A-Za-z0-9])"),
]


class ConfigError(Exception):
    """Raised for any configuration or input problem (exit code 1)."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def to_text(value: Any) -> str:
    """Render an arbitrary JSON value as text for prompts/comparisons."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def render_template(template: str, row: Dict[str, Any], row_index: int) -> str:
    """Substitute {field} placeholders from ``row``.

    Raises ConfigError naming the row index and the first missing field.
    """
    missing: List[str] = []

    def repl(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in row:
            missing.append(name)
            return match.group(0)
        return to_text(row[name])

    rendered = PLACEHOLDER_RE.sub(repl, template)
    if missing:
        raise ConfigError(
            "row %d: missing field %r referenced by prompt template"
            % (row_index, missing[0])
        )
    return rendered


def render_with_response(
    template: str, row: Dict[str, Any], row_index: int, response: str
) -> str:
    """Render a template that may reference row fields and ``__response__``.

    A row field can itself expand to text containing ``{__response__}``; that
    second-level placeholder is substituted after the row fields are expanded.
    """
    context = dict(row)
    context[RESPONSE_KEY] = response
    rendered = render_template(template, context, row_index)
    if RESPONSE_PLACEHOLDER in rendered:
        rendered = rendered.replace(RESPONSE_PLACEHOLDER, response)
    return rendered


def template_fields(template: str) -> List[str]:
    return list(dict.fromkeys(PLACEHOLDER_RE.findall(template or "")))


def row_template_fields(template: str) -> List[str]:
    """Template fields that must come from the input row."""
    return [name for name in template_fields(template) if name != RESPONSE_KEY]


def extract_value(text: str, method: str) -> Optional[str]:
    """Apply an extract method to a model response."""
    if method == "full":
        return text
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return None
    if method == "last_number":
        matches = NUMBER_RE.findall(text)
        if not matches:
            return None
        return matches[-1].replace(",", "")
    if method == "first_number":
        match = NUMBER_RE.search(text)
        if match is None:
            return None
        return match.group(0).replace(",", "")
    if method == "letter":
        for pattern in LETTER_RES:
            match = pattern.search(text)
            if match is not None:
                return match.group(1)
        return None
    raise ConfigError("unknown extract method: %r" % (method,))


def _normalize(value: str) -> str:
    out = value.strip()
    out = out.replace(",", "")
    out = out.lstrip("$").strip()
    out = out.rstrip(".").strip()
    return out


def _as_float(value: str) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def answers_match(extracted: str, expected: str) -> bool:
    if extracted == expected:
        return True
    left, right = _normalize(extracted), _normalize(expected)
    if left == right:
        return True
    left_num, right_num = _as_float(left), _as_float(right)
    if left_num is not None and right_num is not None:
        return math.isclose(left_num, right_num, rel_tol=1e-9, abs_tol=1e-9)
    return left.casefold() == right.casefold()


def _to_score(extracted: Optional[str]) -> Optional[float]:
    if extracted is None:
        return None
    number = _as_float(_normalize(extracted))
    if number is None:
        found = NUMBER_RE.search(extracted)
        if found is None:
            return None
        number = _as_float(found.group(0).replace(",", ""))
    return number


def _json_number(value: Optional[float]) -> Optional[Any]:
    if value is None:
        return None
    if float(value).is_integer():
        return int(value)
    return value


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


class Evaluation:
    def __init__(
        self,
        type_: str,
        answer_field: Optional[str] = None,
        extract: Optional[str] = None,
        pattern: Optional[str] = None,
        judge_system: Optional[str] = None,
        judge_user: Optional[str] = None,
        threshold: Optional[float] = None,
        model: Optional[str] = None,
        command_template: Optional[str] = None,
        success_exit_code: int = 0,
    ) -> None:
        self.type = type_
        self.answer_field = answer_field
        self.extract = extract
        self.pattern_source = pattern
        self.pattern = re.compile(pattern) if pattern is not None else None
        self.judge_system = judge_system
        self.judge_user = judge_user
        self.threshold = threshold
        self.model = model
        self.command_template = command_template
        self.success_exit_code = success_exit_code

    def row_fields(self) -> List[str]:
        """Row fields the evaluation needs, beyond answer_field."""
        fields: List[str] = []
        for template in (self.judge_system, self.judge_user, self.command_template):
            if not template:
                continue
            for name in row_template_fields(template):
                if name not in fields:
                    fields.append(name)
        return fields

    def evaluate(self, text: str, row: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Return (passed, extracted_answer) for one response (sync types)."""
        if self.type == "exact_match":
            extracted = extract_value(text, self.extract or "full")
            expected = to_text(row.get(self.answer_field))
            passed = extracted is not None and answers_match(extracted, expected)
            return passed, extracted

        if self.type == "contains":
            expected = to_text(row.get(self.answer_field))
            passed = expected in text
            if self.extract:
                extracted = extract_value(text, self.extract)
            else:
                extracted = expected if passed else None
            return passed, extracted

        # regex
        match = self.pattern.search(text) if self.pattern else None
        passed = match is not None
        if self.extract:
            extracted = extract_value(text, self.extract)
        elif match is None:
            extracted = None
        elif match.groups():
            extracted = match.group(1)
        else:
            extracted = match.group(0)
        return passed, extracted


class ICLExample:
    """One in-context example: a row-shaped input and a verbatim reply."""

    def __init__(self, inputs: Dict[str, Any], output: str) -> None:
        self.inputs = inputs
        self.output = output


class ICLSetup:
    """A named collection of in-context examples."""

    def __init__(self, name: str, examples: List[ICLExample]) -> None:
        self.name = name
        self.examples = examples

    def selected(self, k: Optional[int]) -> List[ICLExample]:
        """The examples actually used: all of them, or the first ``k``."""
        if k is None or k >= len(self.examples):
            return self.examples
        return self.examples[:k]


def _parse_icl_example(raw: Any, label: str, strict: bool) -> ICLExample:
    """Validate one ``{"input": {...}, "output": "..."}`` record."""
    if not isinstance(raw, dict):
        raise ConfigError("%s must be an object with 'input' and 'output'" % label)
    if "input" not in raw:
        raise ConfigError("%s is missing required key 'input'" % label)
    if "output" not in raw:
        raise ConfigError("%s is missing required key 'output'" % label)
    inputs = raw["input"]
    if not isinstance(inputs, dict):
        raise ConfigError("%s: 'input' must be an object" % label)
    output = raw["output"]
    if isinstance(output, str):
        text = output
    elif strict or isinstance(output, (list, dict)) or output is None:
        raise ConfigError("%s: 'output' must be a string" % label)
    else:
        text = to_text(output)
    return ICLExample(dict(inputs), text)


def load_icl_file(path: str, label: str) -> List[ICLExample]:
    """Read a JSONL file of in-context examples (strict; errors exit 1)."""
    if not os.path.exists(path):
        raise ConfigError("%s: ICL example file not found: %s" % (label, path))
    examples: List[ICLExample] = []
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError as exc:
        raise ConfigError("%s: could not read ICL file %s: %s" % (label, path, exc))
    try:
        for lineno, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ConfigError(
                    "%s: %s line %d is not valid JSON: %s"
                    % (label, path, lineno, exc)
                )
            examples.append(
                _parse_icl_example(raw, "%s: %s line %d" % (label, path, lineno), True)
            )
    except OSError as exc:
        raise ConfigError("%s: could not read ICL file %s: %s" % (label, path, exc))
    finally:
        handle.close()
    return examples


class ICLConfig:
    def __init__(
        self, setups: List[ICLSetup], k: Optional[int], strategy: str
    ) -> None:
        self.setups = setups
        self.k = k
        self.strategy = strategy


def build_icl_config(raw: Any, args: Any, label: str, config_dir: str) -> ICLConfig:
    icl = _require_mapping(raw, label)

    setups_raw = icl.get("setups")
    if setups_raw is None:
        raise ConfigError("%s.setups is required" % label)
    if not isinstance(setups_raw, list) or not setups_raw:
        raise ConfigError("%s.setups must be a non-empty list" % label)

    setups: List[ICLSetup] = []
    for position, item in enumerate(setups_raw):
        slabel = "%s.setups[%d]" % (label, position)
        setup_raw = _require_mapping(item, slabel)
        name = setup_raw.get("name")
        if name is None or not str(name).strip():
            raise ConfigError("%s.name is required" % slabel)
        name = str(name)

        has_examples = setup_raw.get("examples") is not None
        has_file = setup_raw.get("file") is not None
        if has_examples == has_file:
            raise ConfigError(
                "%s must define exactly one of 'examples' or 'file'" % slabel
            )

        if has_file:
            file_path = to_text(setup_raw["file"])
            if not os.path.isabs(file_path):
                file_path = os.path.join(config_dir, file_path)
            examples = load_icl_file(file_path, slabel)
        else:
            raw_examples = setup_raw["examples"]
            if not isinstance(raw_examples, list):
                raise ConfigError("%s.examples must be a list" % slabel)
            examples = [
                _parse_icl_example(entry, "%s.examples[%d]" % (slabel, index), False)
                for index, entry in enumerate(raw_examples)
            ]
        setups.append(ICLSetup(name, examples))

    k_raw = _arg(args, "icl_k") if _arg(args, "icl_k") is not None else icl.get("k")
    k = None if k_raw is None else _as_nonnegative_int(k_raw, "%s.k" % label)

    strategy_raw = (
        _arg(args, "icl_strategy")
        if _arg(args, "icl_strategy") is not None
        else icl.get("strategy", "fixed")
    )
    strategy = str(strategy_raw).strip().lower()
    if strategy not in ICL_STRATEGIES:
        raise ConfigError(
            "%s.strategy must be one of %s, got %r"
            % (label, ", ".join(ICL_STRATEGIES), strategy)
        )

    return ICLConfig(setups, k, strategy)


class TaskConfig:
    def __init__(self) -> None:
        self.name: str = "task"
        self.api_url: str = ""
        self.model: str = ""
        self.rpm: int = 60
        self.system_template: Optional[str] = None
        self.user_template: Optional[str] = None
        self.scheme: str = "greedy"
        self.temperature: float = 0.0
        self.max_tokens: int = 512
        self.n: int = 1
        self.evaluation: Optional[Evaluation] = None
        self.output_field: str = "output"
        self.concurrency: int = 0
        self.timeout: float = 600.0
        self.input_path: Optional[str] = None
        self.output_path: Optional[str] = None
        self.icl: Optional[ICLConfig] = None
        self.num_solutions: int = 1
        self.max_attempts_setting: Optional[int] = None

    @property
    def endpoint(self) -> str:
        return self.api_url.rstrip("/") + "/v1/chat/completions"

    @property
    def max_attempts(self) -> int:
        return self.n if self.scheme == "rejection" else 1

    @property
    def icl_setups(self) -> List[ICLSetup]:
        return self.icl.setups if self.icl is not None else []

    @property
    def icl_k(self) -> Optional[int]:
        return self.icl.k if self.icl is not None else None

    @property
    def icl_strategy(self) -> str:
        return self.icl.strategy if self.icl is not None else "fixed"

    @property
    def multi_output(self) -> bool:
        """True when this task uses the Part 3 list output format."""
        return self.icl is not None or self.num_solutions > 1

    def resolved_max_attempts(self) -> int:
        """Attempt budget for rejection sampling in the Part 3 format."""
        if self.max_attempts_setting is not None:
            return self.max_attempts_setting
        return 3 * self.num_solutions

    @property
    def judge_model(self) -> str:
        if self.evaluation is not None and self.evaluation.model:
            return self.evaluation.model
        return self.model

    def prompt_fields(self) -> List[str]:
        fields = template_fields(self.system_template or "")
        for field in template_fields(self.user_template or ""):
            if field not in fields:
                fields.append(field)
        return fields


def _require_mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError("%s must be a mapping" % label)
    return value


def _as_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("%s must be a positive integer" % label)
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("%s must be a positive integer, got %r" % (label, value))
    if number < 1:
        raise ConfigError("%s must be a positive integer, got %r" % (label, value))
    return number


def _as_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("%s must be a non-negative integer" % label)
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("%s must be a non-negative integer, got %r" % (label, value))
    if number < 0:
        raise ConfigError("%s must be a non-negative integer, got %r" % (label, value))
    return number


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("%s must be an integer" % label)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("%s must be an integer, got %r" % (label, value))


def _as_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("%s must be a number" % label)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("%s must be a number, got %r" % (label, value))


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``override`` onto ``base``; nested mappings merge key by key."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _arg(args: Any, name: str) -> Any:
    return getattr(args, name, None)


def build_task_config(
    name: str, task: Dict[str, Any], args: Any, label: str, config_dir: str = "."
) -> TaskConfig:
    """Turn one (already merged) task mapping into a TaskConfig."""
    cfg = TaskConfig()
    cfg.name = name

    api_url = _arg(args, "api_url") if _arg(args, "api_url") is not None else task.get("api_url")
    if not api_url or not str(api_url).strip():
        raise ConfigError("%s.api_url is required" % label)
    cfg.api_url = str(api_url).strip()

    model = _arg(args, "model") if _arg(args, "model") is not None else task.get("model")
    if not model or not str(model).strip():
        raise ConfigError("%s.model is required" % label)
    cfg.model = str(model).strip()

    rpm = _arg(args, "rpm") if _arg(args, "rpm") is not None else task.get("rpm", 60)
    cfg.rpm = _as_positive_int(rpm, "%s.rpm" % label)

    if "prompt" not in task or task.get("prompt") is None:
        raise ConfigError("%s.prompt is required" % label)
    prompt = _require_mapping(task["prompt"], "%s.prompt" % label)
    system = prompt.get("system")
    user = prompt.get("user")
    if system is None and user is None:
        raise ConfigError("%s.prompt must define 'system' and/or 'user'" % label)
    cfg.system_template = None if system is None else to_text(system)
    cfg.user_template = None if user is None else to_text(user)

    generation = _require_mapping(task.get("generation") or {}, "%s.generation" % label)

    scheme = (
        _arg(args, "scheme")
        if _arg(args, "scheme") is not None
        else generation.get("scheme", "greedy")
    )
    scheme = str(scheme).strip().lower()
    if scheme not in SCHEMES:
        raise ConfigError(
            "%s.generation.scheme must be one of %s, got %r"
            % (label, ", ".join(SCHEMES), scheme)
        )
    cfg.scheme = scheme

    max_tokens = (
        _arg(args, "max_tokens")
        if _arg(args, "max_tokens") is not None
        else generation.get("max_tokens", 512)
    )
    cfg.max_tokens = _as_positive_int(max_tokens, "%s.generation.max_tokens" % label)

    temp_raw = (
        _arg(args, "temperature")
        if _arg(args, "temperature") is not None
        else generation.get("temperature")
    )
    if scheme == "greedy":
        cfg.temperature = 0.0  # greedy always forces temperature 0.0
    else:
        if temp_raw is None:
            cfg.temperature = 1.0
        else:
            cfg.temperature = _as_number(temp_raw, "%s.generation.temperature" % label)
        if cfg.temperature <= 0:
            raise ConfigError(
                "%s.generation.temperature must be > 0 for scheme %r, got %s"
                % (label, scheme, cfg.temperature)
            )

    n_raw = _arg(args, "n") if _arg(args, "n") is not None else generation.get("n", 1)
    cfg.n = _as_positive_int(n_raw, "%s.generation.n" % label)

    if generation.get("max_attempts") is not None:
        cfg.max_attempts_setting = _as_positive_int(
            generation.get("max_attempts"), "%s.generation.max_attempts" % label
        )

    num_solutions = (
        _arg(args, "num_solutions")
        if _arg(args, "num_solutions") is not None
        else task.get("num_solutions", 1)
    )
    cfg.num_solutions = _as_positive_int(num_solutions, "%s.num_solutions" % label)

    if task.get("icl") is not None:
        cfg.icl = build_icl_config(task["icl"], args, "%s.icl" % label, config_dir)
        validate_icl_examples(cfg, "%s.icl" % label)

    evaluation_raw = task.get("evaluation")
    if evaluation_raw is not None:
        cfg.evaluation = build_evaluation(evaluation_raw, args, "%s.evaluation" % label)

    if cfg.scheme == "rejection" and cfg.evaluation is None:
        raise ConfigError("%s.evaluation is required for scheme 'rejection'" % label)

    output_field = task.get("output_field")
    if output_field is None or not str(output_field).strip():
        raise ConfigError("%s.output_field is required" % label)
    cfg.output_field = str(output_field)

    if _arg(args, "concurrency") is not None:
        cfg.concurrency = _as_positive_int(_arg(args, "concurrency"), "--concurrency")
    else:
        # Enough in-flight requests to keep a server with `rpm` capacity busy
        # even when individual requests sit in its queue for a while.
        cfg.concurrency = min(max(cfg.rpm, 8), 512)

    return cfg


def render_icl_input(cfg: TaskConfig, example: "ICLExample") -> str:
    """The user turn for one in-context example."""
    if cfg.user_template is None:
        return json.dumps(example.inputs, ensure_ascii=False, sort_keys=True)
    return render_template(cfg.user_template, example.inputs, 0)


def validate_icl_examples(cfg: TaskConfig, label: str) -> None:
    """Fail fast if an example cannot be rendered with prompt.user."""
    if cfg.icl is None:
        return
    for setup in cfg.icl.setups:
        for index, example in enumerate(setup.selected(cfg.icl.k)):
            try:
                render_icl_input(cfg, example)
            except ConfigError as exc:
                raise ConfigError(
                    "%s: setup %r example %d cannot be rendered with prompt.user: %s"
                    % (label, setup.name, index, exc)
                )


def build_evaluation(raw: Any, args: Any, label: str) -> Evaluation:
    evaluation = _require_mapping(raw, label)
    eval_type = evaluation.get("type")
    if eval_type is None:
        raise ConfigError("%s.type is required" % label)
    eval_type = str(eval_type).strip()
    if eval_type not in EVAL_TYPES:
        raise ConfigError(
            "%s.type must be one of %s, got %r" % (label, ", ".join(EVAL_TYPES), eval_type)
        )

    answer_field = evaluation.get("answer_field")
    pattern = evaluation.get("pattern")
    extract = evaluation.get("extract")

    if eval_type in ("exact_match", "contains"):
        if answer_field is None or not str(answer_field).strip():
            raise ConfigError("%s.answer_field is required for type %r" % (label, eval_type))
        answer_field = str(answer_field)
    elif eval_type == "regex":
        if pattern is None or not str(pattern):
            raise ConfigError("%s.pattern is required for type 'regex'" % label)
        answer_field = str(answer_field) if answer_field is not None else None
    else:
        answer_field = str(answer_field) if answer_field is not None else None

    if pattern is not None:
        pattern = to_text(pattern)
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError("%s.pattern is not a valid regex: %s" % (label, exc))

    if extract is not None:
        extract = str(extract).strip()
        if extract not in EXTRACT_METHODS:
            raise ConfigError(
                "%s.extract must be one of %s, got %r"
                % (label, ", ".join(EXTRACT_METHODS), extract)
            )

    judge_system: Optional[str] = None
    judge_user: Optional[str] = None
    threshold: Optional[float] = None
    model: Optional[str] = None
    command_template: Optional[str] = None
    success_exit_code = 0

    if eval_type == "llm_judge":
        judge_raw = evaluation.get("judge_prompt")
        if judge_raw is None:
            raise ConfigError("%s.judge_prompt is required for type 'llm_judge'" % label)
        judge_prompt = _require_mapping(judge_raw, "%s.judge_prompt" % label)
        system = judge_prompt.get("system")
        user = judge_prompt.get("user")
        if system is None and user is None:
            raise ConfigError(
                "%s.judge_prompt must define 'system' and/or 'user'" % label
            )
        judge_system = None if system is None else to_text(system)
        judge_user = None if user is None else to_text(user)

        if evaluation.get("threshold") is None:
            raise ConfigError("%s.threshold is required for type 'llm_judge'" % label)
        threshold = _as_number(evaluation.get("threshold"), "%s.threshold" % label)

        if extract is None:
            extract = "first_number"

        eval_model = _arg(args, "eval_model")
        if eval_model is not None and str(eval_model).strip():
            model = str(eval_model).strip()
        elif evaluation.get("model") is not None and str(evaluation["model"]).strip():
            model = str(evaluation["model"]).strip()

    if eval_type == "script":
        command_template = evaluation.get("command_template")
        if command_template is None or not str(command_template).strip():
            raise ConfigError(
                "%s.command_template is required for type 'script'" % label
            )
        command_template = to_text(command_template)
        if evaluation.get("success_exit_code") is not None:
            success_exit_code = _as_int(
                evaluation.get("success_exit_code"), "%s.success_exit_code" % label
            )

    return Evaluation(
        eval_type,
        answer_field,
        extract,
        pattern,
        judge_system=judge_system,
        judge_user=judge_user,
        threshold=threshold,
        model=model,
        command_template=command_template,
        success_exit_code=success_exit_code,
    )


def read_config_file(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise ConfigError("config file not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError("could not parse YAML config %s: %s" % (path, exc))
    except OSError as exc:
        raise ConfigError("could not read config %s: %s" % (path, exc))

    if raw is None:
        raise ConfigError("config file is empty: %s" % path)
    return _require_mapping(raw, "config")


def is_multi_task(raw: Dict[str, Any]) -> bool:
    """A top-level 'task' key always means the Part 1 single-task format."""
    if "task" in raw:
        return False
    return "tasks" in raw


def load_config(path: str, args: Any) -> TaskConfig:
    """Load a single-task (Part 1) config."""
    raw = read_config_file(path)
    if is_multi_task(raw):
        raise ConfigError("config %s defines multiple tasks" % path)

    if "task" in raw:
        task = _require_mapping(raw["task"], "'task'")
    elif "prompt" in raw:
        task = raw  # tolerate a config written without the 'task' wrapper
    else:
        raise ConfigError("config must contain a 'task' section")

    name = str(task.get("name") or "task")
    config_dir = os.path.dirname(os.path.abspath(path))
    return build_task_config(name, task, args, "task", config_dir)


def load_multi_config(
    path: str, args: Any, selected: Optional[Sequence[str]] = None
) -> List[TaskConfig]:
    """Load a `defaults` + `tasks` config, building only the selected tasks."""
    raw = read_config_file(path)
    defaults = _require_mapping(raw.get("defaults") or {}, "defaults")
    tasks_raw = raw.get("tasks")
    if tasks_raw is None:
        raise ConfigError("config must contain a 'tasks' section")
    tasks = _require_mapping(tasks_raw, "tasks")
    if not tasks:
        raise ConfigError("config 'tasks' section is empty")

    names = list(tasks.keys())
    if selected:
        unknown = [name for name in selected if name not in tasks]
        if unknown:
            raise ConfigError(
                "unknown task %r; config defines: %s"
                % (unknown[0], ", ".join(str(n) for n in names))
            )
        names = [name for name in names if name in set(selected)]

    config_dir = os.path.dirname(os.path.abspath(path))
    configs: List[TaskConfig] = []
    for name in names:
        merged = deep_merge(defaults, _require_mapping(tasks[name], "tasks.%s" % name))
        merged.pop("name", None)
        configs.append(
            build_task_config(str(name), merged, args, "tasks.%s" % name, config_dir)
        )
    return configs


def load_rows(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        raise ConfigError("input file not found: %s" % path)
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ConfigError(
                        "input line %d is not valid JSON: %s" % (lineno + 1, exc)
                    )
                if not isinstance(obj, dict):
                    raise ConfigError(
                        "input line %d must be a JSON object" % (lineno + 1)
                    )
                rows.append(obj)
    except OSError as exc:
        raise ConfigError("could not read input %s: %s" % (path, exc))
    return rows


def validate_rows(cfg: TaskConfig, rows: List[Dict[str, Any]]) -> None:
    """Fail fast (exit 1) before any API call if a row cannot be used."""
    fields = cfg.prompt_fields()
    extra_fields: List[str] = []
    answer_field = None
    if cfg.evaluation is not None:
        extra_fields = cfg.evaluation.row_fields()
        if cfg.evaluation.answer_field:
            answer_field = cfg.evaluation.answer_field

    for index, row in enumerate(rows):
        for field in fields:
            if field not in row:
                raise ConfigError(
                    "row %d: missing field %r referenced by prompt template"
                    % (index, field)
                )
        if answer_field is not None and answer_field not in row:
            raise ConfigError(
                "row %d: missing field %r required by task.evaluation.answer_field"
                % (index, answer_field)
            )
        for field in extra_fields:
            if field not in row:
                raise ConfigError(
                    "row %d: missing field %r referenced by task.evaluation"
                    % (index, field)
                )


# --------------------------------------------------------------------------- #
# API client
# --------------------------------------------------------------------------- #


class Stats:
    def __init__(self) -> None:
        self.api_calls = 0
        self.first_start: Optional[float] = None
        self.last_end: Optional[float] = None

    def mark(self, start: float, end: float) -> None:
        if self.first_start is None or start < self.first_start:
            self.first_start = start
        if self.last_end is None or end > self.last_end:
            self.last_end = end

    def merge(self, other: "Stats") -> None:
        self.api_calls += other.api_calls
        if other.first_start is not None:
            if self.first_start is None or other.first_start < self.first_start:
                self.first_start = other.first_start
        if other.last_end is not None:
            if self.last_end is None or other.last_end > self.last_end:
                self.last_end = other.last_end

    @property
    def elapsed(self) -> float:
        if self.first_start is None or self.last_end is None:
            return 0.0
        return max(0.0, self.last_end - self.first_start)


class CallResult:
    def __init__(
        self,
        ok: bool,
        content: str = "",
        meta: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        self.ok = ok
        self.content = content
        self.meta = meta or {}
        self.error = error


async def call_api(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    messages: List[Dict[str, str]],
    stats: Stats,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
) -> CallResult:
    """One logical attempt: up to MAX_HTTP_TRIES requests, retrying 5xx."""
    model = cfg.model if model is None else model
    temperature = cfg.temperature if temperature is None else temperature
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": cfg.max_tokens,
    }
    last_error = "request failed"
    last_latency_ms = 0

    for attempt_index in range(MAX_HTTP_TRIES):
        start = time.monotonic()
        stats.api_calls += 1
        retryable = False
        try:
            async with session.post(cfg.endpoint, json=payload) as response:
                body = await response.read()
                end = time.monotonic()
                stats.mark(start, end)
                last_latency_ms = int(round((end - start) * 1000))
                status = response.status
                if status >= 500:
                    last_error = "HTTP %d" % status
                    retryable = True
                elif status >= 400:
                    return CallResult(
                        False,
                        meta=_error_meta(model, last_latency_ms, "HTTP %d" % status),
                        error="HTTP %d" % status,
                    )
                else:
                    try:
                        data = json.loads(body.decode("utf-8"))
                        choice = data["choices"][0]
                        content = choice.get("message", {}).get("content")
                        if content is None:
                            content = ""
                        usage = data.get("usage") or {}
                        meta = {
                            "model": model,
                            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                            "completion_tokens": int(
                                usage.get("completion_tokens") or 0
                            ),
                            "total_tokens": int(usage.get("total_tokens") or 0),
                            "latency_ms": last_latency_ms,
                            "finish_reason": choice.get("finish_reason"),
                        }
                        return CallResult(True, content=str(content), meta=meta)
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                        message = "malformed API response: %s" % exc
                        return CallResult(
                            False,
                            meta=_error_meta(model, last_latency_ms, message),
                            error=message,
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            end = time.monotonic()
            stats.mark(start, end)
            last_latency_ms = int(round((end - start) * 1000))
            last_error = "%s: %s" % (type(exc).__name__, exc) if str(exc) else type(exc).__name__
            retryable = True

        if not retryable:
            break
        if attempt_index < MAX_HTTP_TRIES - 1:
            await asyncio.sleep(min(0.2 * (2 ** attempt_index), 2.0))

    return CallResult(
        False, meta=_error_meta(model, last_latency_ms, last_error), error=last_error
    )


def _error_meta(model: str, latency_ms: int, error: str) -> Dict[str, Any]:
    return {
        "model": model,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latency_ms": latency_ms,
        "finish_reason": None,
        "error": error,
    }


# --------------------------------------------------------------------------- #
# Evaluation backends that need to do work (API call / subprocess)
# --------------------------------------------------------------------------- #


async def run_script_evaluation(
    cfg: TaskConfig, row: Dict[str, Any], index: int, response: str
) -> bool:
    """Render and run the shell command; exit code decides pass/fail."""
    evaluation = cfg.evaluation
    assert evaluation is not None and evaluation.command_template is not None
    command = render_with_response(evaluation.command_template, row, index, response)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group, so a timeout kills the tree
        )
    except OSError:
        return False

    try:
        # stdout/stderr are captured but deliberately not surfaced in output.
        await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT)
    except asyncio.TimeoutError:
        await _terminate(proc)
        return False  # timeout is a failed evaluation

    return proc.returncode == evaluation.success_exit_code


async def _terminate(proc: "asyncio.subprocess.Process") -> None:
    """Kill a timed-out command and everything it spawned."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
    try:
        # The process group is gone; this only reaps it.
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except (asyncio.TimeoutError, ProcessLookupError, OSError):
        pass


async def run_judge_evaluation(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    response: str,
    stats: Stats,
) -> Tuple[bool, Optional[str], Optional[float], Dict[str, Any]]:
    """Ask the judge model to score a response."""
    evaluation = cfg.evaluation
    assert evaluation is not None

    messages: List[Dict[str, str]] = []
    if evaluation.judge_system is not None:
        messages.append(
            {
                "role": "system",
                "content": render_with_response(
                    evaluation.judge_system, row, index, response
                ),
            }
        )
    if evaluation.judge_user is not None:
        messages.append(
            {
                "role": "user",
                "content": render_with_response(
                    evaluation.judge_user, row, index, response
                ),
            }
        )

    call = await call_api(
        session, cfg, messages, stats, model=cfg.judge_model, temperature=0.0
    )
    if not call.ok:
        return False, None, None, call.meta

    extracted = extract_value(call.content, evaluation.extract or "first_number")
    score = _to_score(extracted)
    threshold = evaluation.threshold if evaluation.threshold is not None else 0.0
    passed = score is not None and score >= threshold
    return passed, extracted, score, call.meta


async def evaluate_response(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    response: str,
    stats: Stats,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Return (passed, extracted_answer, extra) for one generated response."""
    evaluation = cfg.evaluation
    assert evaluation is not None

    if evaluation.type == "script":
        passed = await run_script_evaluation(cfg, row, index, response)
        return passed, None, {}

    if evaluation.type == "llm_judge":
        passed, extracted, score, judge_meta = await run_judge_evaluation(
            session, cfg, row, index, response, stats
        )
        return passed, extracted, {"judge_score": score, "judge_meta": judge_meta}

    passed, extracted = evaluation.evaluate(response, row)
    return passed, extracted, {}


# --------------------------------------------------------------------------- #
# Row processing
# --------------------------------------------------------------------------- #


def build_messages(
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    setup: Optional[ICLSetup] = None,
) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    if cfg.system_template is not None:
        messages.append(
            {"role": "system", "content": render_template(cfg.system_template, row, index)}
        )
    if setup is not None:
        # Examples sit between the system message and the final user message as
        # alternating user/assistant turns.
        for example in setup.selected(cfg.icl_k):
            messages.append({"role": "user", "content": render_icl_input(cfg, example)})
            messages.append({"role": "assistant", "content": example.output})
    if cfg.user_template is not None:
        messages.append(
            {"role": "user", "content": render_template(cfg.user_template, row, index)}
        )
    return messages


def select_setup(
    cfg: TaskConfig, attempt_index: int, rng: "random.Random"
) -> Optional[ICLSetup]:
    """Pick the ICL setup for one attempt according to icl.strategy."""
    setups = cfg.icl_setups
    if not setups:
        return None
    strategy = cfg.icl_strategy
    if strategy == "random":
        return rng.choice(setups)
    if strategy == "round_robin":
        return setups[attempt_index % len(setups)]
    return setups[0]  # fixed


def setup_name(setup: Optional[ICLSetup]) -> Optional[str]:
    return setup.name if setup is not None else None


MULTI_ATTEMPT_CAP = 10000  # guards against a pathological attempt budget


def _greedy_plan(cfg: TaskConfig, rng: "random.Random") -> List[Optional[ICLSetup]]:
    """Setups a greedy run walks through, at most once each."""
    setups = cfg.icl_setups
    if not setups:
        return [None]
    if cfg.num_solutions > 1:
        # Re-running the same setup at temperature 0 would only repeat itself,
        # so the declared setups are the whole budget.
        return list(setups)
    return [select_setup(cfg, 0, rng)]


async def process_row_multi(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    stats: Stats,
) -> Dict[str, Any]:
    """Collect up to ``num_solutions`` solutions for one row (list format)."""
    rng = random.Random()
    plan: Optional[List[Optional[ICLSetup]]] = None

    if cfg.scheme == "greedy":
        plan = _greedy_plan(cfg, rng)
        limit = len(plan)
    elif cfg.scheme == "sample":
        limit = cfg.num_solutions
    else:  # rejection
        limit = min(cfg.resolved_max_attempts(), MULTI_ATTEMPT_CAP)

    outputs: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    attempts = 0

    for attempt_index in range(limit):
        if len(outputs) >= cfg.num_solutions:
            break
        setup = plan[attempt_index] if plan is not None else select_setup(
            cfg, attempt_index, rng
        )
        name = setup_name(setup)
        messages = build_messages(cfg, row, index, setup)

        attempts += 1
        call = await call_api(session, cfg, messages, stats)
        meta = dict(call.meta)
        meta["icl_setup"] = name

        if not call.ok:
            meta["evaluation_passed"] = None if cfg.evaluation is None else False
            metas.append(meta)
            continue

        if cfg.evaluation is None:
            meta["evaluation_passed"] = None
            metas.append(meta)
            outputs.append({cfg.output_field: call.content, "icl_setup": name})
            continue

        passed, _extracted, extra = await evaluate_response(
            session, cfg, row, index, call.content, stats
        )
        if "judge_meta" in extra:
            meta["judge_meta"] = extra["judge_meta"]
        meta["evaluation_passed"] = passed
        metas.append(meta)

        # Rejection sampling keeps only passing solutions; the other schemes
        # keep everything the API returned and merely record the verdict.
        if passed or cfg.scheme != "rejection":
            outputs.append({cfg.output_field: call.content, "icl_setup": name})

    if cfg.evaluation is None:
        passed_count = len(outputs)
    else:
        passed_count = sum(1 for meta in metas if meta.get("evaluation_passed") is True)

    return {
        "input": row,
        "output": outputs,
        "result": {
            "passed": passed_count,
            "failed": attempts - passed_count,
            "attempts": attempts,
        },
        "meta": metas,
    }


async def process_row(
    session: "aiohttp.ClientSession",
    cfg: TaskConfig,
    row: Dict[str, Any],
    index: int,
    stats: Stats,
) -> Dict[str, Any]:
    if cfg.multi_output:
        return await process_row_multi(session, cfg, row, index, stats)

    messages = build_messages(cfg, row, index)
    metas: List[Dict[str, Any]] = []
    attempts = 0
    content: Optional[str] = None
    extracted: Optional[str] = None
    passed: Optional[bool] = None
    score: Optional[float] = None
    is_judge = cfg.evaluation is not None and cfg.evaluation.type == "llm_judge"

    for _ in range(cfg.max_attempts):
        attempts += 1
        call = await call_api(session, cfg, messages, stats)
        meta = dict(call.meta)
        if not call.ok:
            metas.append(meta)
            content = None
            extracted = None
            score = None
            passed = None if cfg.evaluation is None else False
            break

        if cfg.evaluation is None:
            metas.append(meta)
            content = call.content
            extracted = None
            passed = None
            break

        attempt_passed, attempt_extracted, extra = await evaluate_response(
            session, cfg, row, index, call.content, stats
        )
        if "judge_meta" in extra:
            meta["judge_meta"] = extra["judge_meta"]
        metas.append(meta)
        attempt_score = extra.get("judge_score")

        if attempt_passed:
            content = call.content
            extracted = attempt_extracted
            score = attempt_score
            passed = True
            break

        # Failed evaluation: keep the response for non-rejection schemes.
        if cfg.scheme != "rejection":
            content = call.content
            extracted = attempt_extracted
            score = attempt_score
            passed = False
            break

        content = None
        extracted = None
        score = None
        passed = False

    output = None if content is None else {cfg.output_field: content}
    if output is None:
        extracted = None
        score = None

    result: Dict[str, Any] = {
        "passed": passed,
        "extracted_answer": extracted,
        "attempts": attempts,
    }
    if is_judge:
        result["judge_score"] = _json_number(score)

    return {
        "input": row,
        "output": output,
        "result": result,
        "meta": metas[0] if len(metas) == 1 else metas,
    }


async def run_task(
    cfg: TaskConfig, rows: List[Dict[str, Any]], stats: Stats
) -> List[Dict[str, Any]]:
    results: List[Optional[Dict[str, Any]]] = [None] * len(rows)
    if not rows:
        return []

    queue: "asyncio.Queue[int]" = asyncio.Queue()
    for index in range(len(rows)):  # dispatched in input order
        queue.put_nowait(index)

    worker_count = max(1, min(cfg.concurrency, len(rows)))
    connector = aiohttp.TCPConnector(limit=worker_count, limit_per_host=worker_count)
    timeout = aiohttp.ClientTimeout(total=cfg.timeout, connect=60, sock_connect=60)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:

        async def worker() -> None:
            while True:
                try:
                    index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                results[index] = await process_row(session, cfg, rows[index], index, stats)

        await asyncio.gather(*(worker() for _ in range(worker_count)))

    return [r for r in results if r is not None]


async def run_rows(cfg: TaskConfig, rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Stats]:
    stats = Stats()
    results = await run_task(cfg, rows, stats)
    return results, stats


async def run_tasks(
    jobs: List[Tuple[TaskConfig, List[Dict[str, Any]]]]
) -> List[Tuple[TaskConfig, List[Dict[str, Any]], Stats]]:
    """Run every task concurrently; requests interleave across tasks."""
    stats_list = [Stats() for _ in jobs]
    results: List[List[Optional[Dict[str, Any]]]] = [
        [None] * len(rows) for _cfg, rows in jobs
    ]

    # Round robin over the tasks so the first rows of every task go out
    # together; within a task, rows are still dispatched in input order.
    order: List[Tuple[int, int]] = []
    depth = max([len(rows) for _cfg, rows in jobs] or [0])
    for position in range(depth):
        for task_index, (_cfg, rows) in enumerate(jobs):
            if position < len(rows):
                order.append((task_index, position))

    if not order:
        return [(cfg, [], stats) for (cfg, _rows), stats in zip(jobs, stats_list)]

    queue: "asyncio.Queue[Tuple[int, int]]" = asyncio.Queue()
    for item in order:
        queue.put_nowait(item)

    async with contextlib.AsyncExitStack() as stack:
        sessions: List[aiohttp.ClientSession] = []
        worker_count = 0
        for cfg, rows in jobs:
            count = max(1, min(cfg.concurrency, len(rows))) if rows else 1
            worker_count += count if rows else 0
            connector = aiohttp.TCPConnector(limit=count, limit_per_host=count)
            timeout = aiohttp.ClientTimeout(total=cfg.timeout, connect=60, sock_connect=60)
            sessions.append(
                await stack.enter_async_context(
                    aiohttp.ClientSession(connector=connector, timeout=timeout)
                )
            )

        worker_count = max(1, min(worker_count, len(order)))

        async def worker() -> None:
            while True:
                try:
                    task_index, row_index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                cfg, rows = jobs[task_index]
                results[task_index][row_index] = await process_row(
                    sessions[task_index],
                    cfg,
                    rows[row_index],
                    row_index,
                    stats_list[task_index],
                )

        await asyncio.gather(*(worker() for _ in range(worker_count)))

    return [
        (cfg, [r for r in results[task_index] if r is not None], stats_list[task_index])
        for task_index, (cfg, _rows) in enumerate(jobs)
    ]


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def write_results(path: str, results: List[Dict[str, Any]]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")


def _iter_call_metas(meta: Any) -> Iterator[Dict[str, Any]]:
    entries = meta if isinstance(meta, list) else [meta]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        yield entry
        judge_meta = entry.get("judge_meta")
        if isinstance(judge_meta, dict):
            yield judge_meta


class Tally:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.solutions = 0


def _tally(results: List[Dict[str, Any]]) -> Tally:
    tally = Tally()
    for result in results:
        outcome = result["result"]["passed"]
        output = result["output"]
        if isinstance(output, list):
            # Part 3 list format: a row counts as passed when it produced at
            # least one solution that was kept.
            tally.solutions += len(output)
            if outcome:
                tally.passed += 1
            else:
                tally.failed += 1
        else:
            has_output = output is not None
            tally.solutions += 1 if has_output else 0
            if outcome is True or (outcome is None and has_output):
                tally.passed += 1
            if outcome is False or not has_output:
                tally.failed += 1
        for entry in _iter_call_metas(result["meta"]):
            tally.prompt_tokens += int(entry.get("prompt_tokens") or 0)
            tally.completion_tokens += int(entry.get("completion_tokens") or 0)
    return tally


def build_summary(results: List[Dict[str, Any]], stats: Stats) -> Dict[str, Any]:
    tally = _tally(results)
    elapsed = stats.elapsed
    throughput = (stats.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0

    return {
        "total": len(results),
        "passed": tally.passed,
        "failed": tally.failed,
        "total_prompt_tokens": tally.prompt_tokens,
        "total_completion_tokens": tally.completion_tokens,
        "total_api_calls": stats.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }


def build_multi_summary(
    executed: List[Tuple[TaskConfig, List[Dict[str, Any]], Stats]]
) -> Dict[str, Any]:
    overall = Stats()
    total = 0
    passed = 0
    failed = 0
    prompt_tokens = 0
    completion_tokens = 0
    tasks: Dict[str, Any] = {}

    for cfg, results, stats in executed:
        overall.merge(stats)
        tally = _tally(results)
        total += len(results)
        passed += tally.passed
        failed += tally.failed
        prompt_tokens += tally.prompt_tokens
        completion_tokens += tally.completion_tokens
        average = tally.solutions / len(results) if results else 0.0
        tasks[cfg.name] = {
            "total": len(results),
            "passed": tally.passed,
            "failed": tally.failed,
            "total_solutions": tally.solutions,
            "avg_solutions_per_input": round(average, 2),
            "total_api_calls": stats.api_calls,
        }

    elapsed = overall.elapsed
    throughput = (overall.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": prompt_tokens,
        "total_completion_tokens": completion_tokens,
        "total_api_calls": overall.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
        "tasks": tasks,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class ArgumentParser(argparse.ArgumentParser):
    """argparse parser that exits 1 (config error) instead of 2 on bad usage."""

    def error(self, message: str) -> "None":  # type: ignore[override]
        self.print_usage(sys.stderr)
        sys.stderr.write("error: %s\n" % message)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="rejector.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run one or more tasks over JSONL inputs")
    run.add_argument(
        "--input",
        action="append",
        default=None,
        help="JSONL input file, or <task>=<path> for a multi-task config",
    )
    run.add_argument(
        "--input-dir",
        dest="input_dir",
        default=None,
        help="directory holding <task_name>.jsonl for a multi-task config",
    )
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--output", required=True, help="JSONL output file or directory")
    run.add_argument(
        "--task",
        dest="tasks",
        action="append",
        default=None,
        help="run only this task (repeatable)",
    )
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument(
        "--eval-model",
        dest="eval_model",
        default=None,
        help="override the judge model for llm_judge tasks",
    )
    run.add_argument("--rpm", default=None)
    run.add_argument("--max-tokens", dest="max_tokens", default=None)
    run.add_argument("--scheme", default=None, choices=list(SCHEMES))
    run.add_argument("--temperature", default=None)
    run.add_argument("--n", default=None)
    run.add_argument(
        "--num-solutions",
        dest="num_solutions",
        default=None,
        help="number of solutions to collect per input",
    )
    run.add_argument(
        "--icl-strategy",
        dest="icl_strategy",
        default=None,
        choices=list(ICL_STRATEGIES),
        help="how to pick an ICL setup for each attempt",
    )
    run.add_argument(
        "--icl-k",
        dest="icl_k",
        default=None,
        help="number of in-context examples to use from the selected setup",
    )
    run.add_argument("--concurrency", default=None, help=argparse.SUPPRESS)
    return parser


def split_input_spec(spec: str) -> Tuple[Optional[str], str]:
    """Split `name=path` into (name, path); plain paths give (None, path)."""
    head, sep, tail = spec.partition("=")
    if not sep:
        return None, spec
    if not head.strip():
        return None, spec
    return head.strip(), tail


def resolve_single_input(args: argparse.Namespace, cfg: TaskConfig) -> str:
    inputs = args.input or []
    if args.input_dir is not None:
        if inputs:
            raise ConfigError("--input and --input-dir cannot be combined")
        path = os.path.join(args.input_dir, "%s.jsonl" % cfg.name)
        if not os.path.exists(path):
            raise ConfigError("input file not found: %s" % path)
        return path
    if not inputs:
        raise ConfigError("--input is required")
    if len(inputs) > 1:
        raise ConfigError("--input may only be given once for a single-task config")
    name, path = split_input_spec(inputs[0])
    if name is not None and name != cfg.name:
        # A plain path that happens to contain '=' is still a path.
        path = inputs[0]
    return path


def multi_task_names(path: str) -> List[str]:
    """Every task name defined by a multi-task config, selected or not."""
    raw = read_config_file(path)
    tasks = raw.get("tasks")
    if not isinstance(tasks, dict):
        return []
    return [str(name) for name in tasks]


def resolve_multi_inputs(
    args: argparse.Namespace, configs: List[TaskConfig], all_names: Sequence[str]
) -> Dict[str, str]:
    """Map each selected task to its input file.

    Unselected tasks are ignored: their inputs are neither required nor read.
    """
    names = [cfg.name for cfg in configs]
    inputs = args.input or []

    if inputs and args.input_dir is not None:
        raise ConfigError(
            "--input and --input-dir are alternative modes; do not combine them"
        )

    mapping: Dict[str, str] = {}

    if args.input_dir is not None:
        if not os.path.isdir(args.input_dir):
            raise ConfigError("input directory not found: %s" % args.input_dir)
        for name in names:
            path = os.path.join(args.input_dir, "%s.jsonl" % name)
            if not os.path.exists(path):
                raise ConfigError("input file not found for task %r: %s" % (name, path))
            mapping[name] = path
        return mapping

    if not inputs:
        raise ConfigError("--input <task>=<path> or --input-dir is required")

    known = set(all_names)
    selected = set(names)
    for spec in inputs:
        name, path = split_input_spec(spec)
        if name is None:
            raise ConfigError(
                "--input must be given as <task>=<path> for a multi-task config, got %r"
                % spec
            )
        if name not in known:
            raise ConfigError("unknown task %r in --input %r" % (name, spec))
        if name in selected:
            mapping[name] = path

    for name in names:
        if name not in mapping:
            raise ConfigError("no input file given for task %r" % name)
    return mapping


def prepare_output_dir(path: str) -> str:
    if os.path.exists(path) and not os.path.isdir(path):
        raise ConfigError("--output must be a directory for a multi-task config: %s" % path)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise ConfigError("could not create output directory %s: %s" % (path, exc))
    return path


def run_single(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config, args)
        if args.tasks:
            unknown = [name for name in args.tasks if name != cfg.name]
            if unknown:
                raise ConfigError(
                    "unknown task %r; config defines: %s" % (unknown[0], cfg.name)
                )
        input_path = resolve_single_input(args, cfg)
        rows = load_rows(input_path)
        validate_rows(cfg, rows)
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    try:
        results, stats = asyncio.run(run_rows(cfg, rows))
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    try:
        write_results(args.output, results)
    except OSError as exc:
        sys.stderr.write("error: could not write output %s: %s\n" % (args.output, exc))
        return EXIT_ERROR

    sys.stdout.write(json.dumps(build_summary(results, stats)) + "\n")
    return EXIT_OK


def run_multi(args: argparse.Namespace) -> int:
    try:
        selected = args.tasks or None
        all_names = multi_task_names(args.config)
        configs = load_multi_config(args.config, args, selected)
        if not configs:
            raise ConfigError("no tasks selected")
        inputs = resolve_multi_inputs(args, configs, all_names)
        output_dir = prepare_output_dir(args.output)

        jobs: List[Tuple[TaskConfig, List[Dict[str, Any]]]] = []
        for cfg in configs:
            cfg.input_path = inputs[cfg.name]
            cfg.output_path = os.path.join(output_dir, "%s.jsonl" % cfg.name)
            rows = load_rows(cfg.input_path)
            validate_rows(cfg, rows)
            jobs.append((cfg, rows))
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    try:
        executed = asyncio.run(run_tasks(jobs))
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    for cfg, results, _stats in executed:
        try:
            write_results(cfg.output_path or "", results)
        except OSError as exc:
            sys.stderr.write(
                "error: could not write output %s: %s\n" % (cfg.output_path, exc)
            )
            return EXIT_ERROR

    sys.stdout.write(json.dumps(build_multi_summary(executed)) + "\n")
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        raw = read_config_file(args.config)
        multi = is_multi_task(raw)
    except ConfigError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR

    return run_multi(args) if multi else run_single(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(EXIT_ERROR)
