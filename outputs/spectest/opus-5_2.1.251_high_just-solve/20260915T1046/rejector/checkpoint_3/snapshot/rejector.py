#!/usr/bin/env python3
"""rejector - run YAML-configured generation tasks against an OpenAI-compatible API.

Single task (part 1):
    python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl

Multiple named tasks (part 2):
    python rejector.py run --config multi.yaml --input gsm8k=math.jsonl --output results/
    python rejector.py run --config multi.yaml --input-dir data/ --output results/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import signal
import string
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import yaml

EXIT_OK = 0
EXIT_ERROR = 1

MAX_RETRIES = 3  # retries after the initial attempt, for HTTP 5xx / transport errors
SCHEMES = ("greedy", "sample", "rejection")
EVAL_TYPES = ("exact_match", "contains", "regex", "script", "llm_judge")
EXTRACT_METHODS = ("last_number", "last_line", "full", "letter", "first_number")
ICL_STRATEGIES = ("fixed", "random", "round_robin")

RESPONSE_KEY = "__response__"
RESPONSE_PLACEHOLDER = "{" + RESPONSE_KEY + "}"
SCRIPT_TIMEOUT = 10.0  # seconds; a timeout is a failed evaluation


class ConfigError(Exception):
    """Configuration or input problem: reported on stderr, exit code 1."""


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


@dataclass
class Evaluation:
    type: str
    answer_field: str | None = None
    extract: str = "full"
    extract_given: bool = False
    pattern: str | None = None
    regex: re.Pattern[str] | None = None
    # script
    command_template: str | None = None
    success_exit_code: int = 0
    # llm_judge
    judge_system: str | None = None
    judge_user: str | None = None
    threshold: float = 0.0
    model: str | None = None
    judge_temperature: float = 0.0
    judge_max_tokens: int | None = None


@dataclass
class IclExample:
    """One in-context example: a row-shaped input plus the assistant reply."""

    input: dict
    output: str


@dataclass
class IclSetup:
    name: str
    examples: list[IclExample] = field(default_factory=list)
    # alternating user/assistant turns, built once from the first `k` examples
    messages: list[dict] = field(default_factory=list)


@dataclass
class IclConfig:
    setups: list[IclSetup]
    strategy: str = "fixed"
    k: int | None = None  # None means "all examples of the selected setup"


@dataclass
class Config:
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
    output_field: str
    evaluation: Evaluation | None = None
    icl: IclConfig | None = None
    num_solutions: int = 1
    max_attempts: int | None = None

    @property
    def list_format(self) -> bool:
        """Part 3 output shape: a list of solutions and one meta entry per attempt."""
        return self.icl is not None or self.num_solutions > 1



def _require_mapping(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"config: '{what}' must be a mapping")
    return value


def _as_int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"config: '{what}' must be an integer")
    try:
        ivalue = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"config: '{what}' must be an integer, got {value!r}") from None
    return ivalue


def _as_float(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"config: '{what}' must be a number")
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"config: '{what}' must be a number, got {value!r}") from None


def deep_merge(base: dict, override: dict) -> dict:
    """Recursive mapping merge: override wins, nested mappings are merged."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def template_fields(template: str, what: str) -> list[str]:
    """Field names referenced by {placeholders} in a template."""
    fields: list[str] = []
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise ConfigError(f"config: invalid placeholder syntax in {what}: {exc}") from None
    for _literal, name, _spec, _conv in parsed:
        if name is None:
            continue
        if name == "":
            raise ConfigError(f"config: positional placeholder '{{}}' not supported in {what}")
        root = name.split(".")[0].split("[")[0]
        if not root:
            raise ConfigError(f"config: invalid placeholder '{{{name}}}' in {what}")
        if root not in fields:
            fields.append(root)
    return fields


def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse YAML config {path}: {exc}") from None
    if raw is None:
        raise ConfigError(f"config file is empty: {path}")
    if not isinstance(raw, dict):
        raise ConfigError("config: top level must be a mapping with a 'task' or 'tasks' key")
    return raw


def is_multi_config(raw: dict) -> bool:
    """A top-level 'task' key means the part 1 single-task format."""
    return "task" not in raw and "tasks" in raw


def build_config(
    task: dict,
    args: argparse.Namespace,
    name: str,
    prefix: str,
    config_dir: str = ".",
) -> Config:
    """Build one task's config. `prefix` labels the section in error messages.

    `config_dir` is the directory of the YAML file; ICL example files resolve
    against it.
    """
    api_url = args.api_url if args.api_url is not None else task.get("api_url")
    if api_url is None or str(api_url).strip() == "":
        raise ConfigError(f"config: '{prefix}.api_url' is required (or pass --api-url)")
    api_url = str(api_url).strip().rstrip("/")

    model = args.model if args.model is not None else task.get("model")
    if model is None or str(model).strip() == "":
        raise ConfigError(f"config: '{prefix}.model' is required (or pass --model)")
    model = str(model)

    rpm_raw = args.rpm if args.rpm is not None else task.get("rpm", 60)
    rpm = _as_int(rpm_raw, f"{prefix}.rpm")
    if rpm <= 0:
        raise ConfigError(f"config: '{prefix}.rpm' must be > 0, got {rpm}")

    if "prompt" not in task:
        raise ConfigError(f"config: missing required section '{prefix}.prompt'")
    prompt = _require_mapping(task["prompt"], f"{prefix}.prompt")
    if "user" not in prompt or prompt["user"] is None:
        raise ConfigError(f"config: '{prefix}.prompt.user' is required")
    user_template = str(prompt["user"])
    system_template = None if prompt.get("system") is None else str(prompt["system"])

    generation = _require_mapping(task.get("generation", {}) or {}, f"{prefix}.generation")

    scheme = args.scheme if args.scheme is not None else generation.get("scheme", "greedy")
    scheme = str(scheme).strip()
    if scheme not in SCHEMES:
        raise ConfigError(
            f"config: '{prefix}.generation.scheme' must be one of {', '.join(SCHEMES)}, "
            f"got {scheme!r}"
        )

    if args.temperature is not None:
        temperature = float(args.temperature)
    elif generation.get("temperature") is not None:
        temperature = _as_float(generation["temperature"], f"{prefix}.generation.temperature")
    else:
        temperature = 0.0

    max_tokens_raw = (
        args.max_tokens if args.max_tokens is not None else generation.get("max_tokens", 512)
    )
    max_tokens = _as_int(max_tokens_raw, f"{prefix}.generation.max_tokens")
    if max_tokens <= 0:
        raise ConfigError(f"config: '{prefix}.generation.max_tokens' must be > 0, got {max_tokens}")

    n_raw = args.n if args.n is not None else generation.get("n", 1)
    n = _as_int(n_raw, f"{prefix}.generation.n")
    if n <= 0:
        raise ConfigError(f"config: '{prefix}.generation.n' must be > 0, got {n}")

    if getattr(args, "num_solutions", None) is not None:
        num_solutions = _as_int(args.num_solutions, "--num-solutions")
        num_label = "--num-solutions"
    else:
        raw_num = task.get("num_solutions")
        if raw_num is None:
            raw_num = generation.get("num_solutions")
        num_solutions = 1 if raw_num is None else _as_int(raw_num, f"{prefix}.num_solutions")
        num_label = f"{prefix}.num_solutions"
    if num_solutions <= 0:
        raise ConfigError(f"config: '{num_label}' must be > 0, got {num_solutions}")

    raw_max_attempts = generation.get("max_attempts")
    if raw_max_attempts is None:
        raw_max_attempts = task.get("max_attempts")
    if raw_max_attempts is None:
        max_attempts = None
    else:
        max_attempts = _as_int(raw_max_attempts, f"{prefix}.generation.max_attempts")
        if max_attempts <= 0:
            raise ConfigError(
                f"config: '{prefix}.generation.max_attempts' must be > 0, got {max_attempts}"
            )

    icl = build_icl(task.get("icl"), args, prefix, config_dir)

    if scheme == "greedy":
        temperature = 0.0
        n = 1
    elif scheme == "sample":
        if temperature <= 0:
            raise ConfigError(
                f"config: scheme 'sample' requires '{prefix}.generation.temperature' > 0, "
                f"got {temperature}"
            )
        n = 1
    else:  # rejection
        if temperature <= 0:
            raise ConfigError(
                f"config: scheme 'rejection' requires '{prefix}.generation.temperature' > 0, "
                f"got {temperature}"
            )

    evaluation = build_evaluation(task.get("evaluation"), scheme, prefix)
    if evaluation is not None and evaluation.type == "llm_judge":
        if getattr(args, "eval_model", None):
            evaluation.model = str(args.eval_model)
        if not evaluation.model:
            evaluation.model = model

    output_field_raw = task.get("output_field", "output")
    if output_field_raw is None or str(output_field_raw).strip() == "":
        raise ConfigError(f"config: '{prefix}.output_field' must be a non-empty string")
    output_field = str(output_field_raw)

    # validates placeholder syntax up front
    template_fields(user_template, f"{prefix}.prompt.user")
    if system_template is not None:
        template_fields(system_template, f"{prefix}.prompt.system")

    if icl is not None:
        build_icl_messages(icl, user_template, prefix)

    if scheme == "rejection" and not (num_solutions == 1 and icl is None):
        # part 3 rejection is bounded by max_attempts, not by generation.n
        if max_attempts is None:
            max_attempts = 3 * num_solutions

    return Config(
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
        output_field=output_field,
        evaluation=evaluation,
        icl=icl,
        num_solutions=num_solutions,
        max_attempts=max_attempts,
    )


def build_evaluation(raw: Any, scheme: str, prefix: str = "task") -> Evaluation | None:
    if raw is None:
        if scheme == "rejection":
            raise ConfigError(f"config: '{prefix}.evaluation' is required for scheme 'rejection'")
        return None

    section = _require_mapping(raw, f"{prefix}.evaluation")
    eval_type = section.get("type")
    if eval_type is None:
        raise ConfigError(f"config: '{prefix}.evaluation.type' is required")
    eval_type = str(eval_type).strip()
    if eval_type not in EVAL_TYPES:
        raise ConfigError(
            f"config: '{prefix}.evaluation.type' must be one of {', '.join(EVAL_TYPES)}, "
            f"got {eval_type!r}"
        )

    answer_field = section.get("answer_field")
    if answer_field is not None:
        answer_field = str(answer_field)

    extract_given = section.get("extract") is not None
    default_extract = "first_number" if eval_type == "llm_judge" else "full"
    extract = section.get("extract") if extract_given else default_extract
    extract = str(extract).strip()
    if extract not in EXTRACT_METHODS:
        raise ConfigError(
            f"config: '{prefix}.evaluation.extract' must be one of {', '.join(EXTRACT_METHODS)}, "
            f"got {extract!r}"
        )

    evaluation = Evaluation(
        type=eval_type,
        answer_field=answer_field,
        extract=extract,
        extract_given=extract_given,
    )

    if eval_type in ("exact_match", "contains"):
        if not answer_field:
            raise ConfigError(
                f"config: evaluation type '{eval_type}' requires '{prefix}.evaluation.answer_field'"
            )
    elif eval_type == "regex":
        pattern = section.get("pattern")
        if pattern is None or str(pattern) == "":
            raise ConfigError(
                f"config: evaluation type 'regex' requires '{prefix}.evaluation.pattern'"
            )
        pattern = str(pattern)
        try:
            evaluation.regex = re.compile(pattern, re.MULTILINE | re.DOTALL)
        except re.error as exc:
            raise ConfigError(f"config: invalid '{prefix}.evaluation.pattern': {exc}") from None
        evaluation.pattern = pattern
    elif eval_type == "script":
        command = section.get("command_template")
        if command is None or str(command).strip() == "":
            raise ConfigError(
                f"config: evaluation type 'script' requires '{prefix}.evaluation.command_template'"
            )
        evaluation.command_template = str(command)
        template_fields(evaluation.command_template, f"{prefix}.evaluation.command_template")
        code = section.get("success_exit_code", 0)
        evaluation.success_exit_code = _as_int(
            0 if code is None else code, f"{prefix}.evaluation.success_exit_code"
        )
    else:  # llm_judge
        if section.get("judge_prompt") is None:
            raise ConfigError(
                f"config: evaluation type 'llm_judge' requires '{prefix}.evaluation.judge_prompt'"
            )
        judge = _require_mapping(section["judge_prompt"], f"{prefix}.evaluation.judge_prompt")
        if judge.get("user") is None:
            raise ConfigError(f"config: '{prefix}.evaluation.judge_prompt.user' is required")
        evaluation.judge_user = str(judge["user"])
        evaluation.judge_system = None if judge.get("system") is None else str(judge["system"])
        template_fields(evaluation.judge_user, f"{prefix}.evaluation.judge_prompt.user")
        if evaluation.judge_system is not None:
            template_fields(evaluation.judge_system, f"{prefix}.evaluation.judge_prompt.system")

        if section.get("threshold") is None:
            raise ConfigError(
                f"config: evaluation type 'llm_judge' requires '{prefix}.evaluation.threshold'"
            )
        evaluation.threshold = _as_float(section["threshold"], f"{prefix}.evaluation.threshold")

        judge_model = section.get("model")
        evaluation.model = None if judge_model is None else str(judge_model)
        if section.get("temperature") is not None:
            evaluation.judge_temperature = _as_float(
                section["temperature"], f"{prefix}.evaluation.temperature"
            )
        if section.get("max_tokens") is not None:
            evaluation.judge_max_tokens = _as_int(
                section["max_tokens"], f"{prefix}.evaluation.max_tokens"
            )
            if evaluation.judge_max_tokens <= 0:
                raise ConfigError(f"config: '{prefix}.evaluation.max_tokens' must be > 0")

    return evaluation



# --------------------------------------------------------------------------
# in-context learning setups
# --------------------------------------------------------------------------


def _icl_example(item: Any, where: str) -> IclExample:
    """Validate one `{"input": {...}, "output": "..."}` record."""
    if not isinstance(item, dict):
        raise ConfigError(f"config: {where} must be a mapping with 'input' and 'output'")
    if "input" not in item:
        raise ConfigError(f"config: {where} is missing 'input'")
    if "output" not in item:
        raise ConfigError(f"config: {where} is missing 'output'")
    example_input = item["input"]
    if not isinstance(example_input, dict):
        raise ConfigError(f"config: {where} 'input' must be a mapping")
    output = item["output"]
    if not isinstance(output, str):
        raise ConfigError(f"config: {where} 'output' must be a string")
    return IclExample(input=dict(example_input), output=output)


def load_icl_file(path: str, where: str) -> list[IclExample]:
    """Read a JSONL file of ICL examples; any malformed line is a config error."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise ConfigError(f"config: {where} file not found: {path}") from None
    except IsADirectoryError:
        raise ConfigError(f"config: {where} file is a directory: {path}") from None
    except OSError as exc:
        raise ConfigError(f"config: {where} could not read file {path}: {exc}") from None

    examples: list[IclExample] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"config: {where} file {path} line {lineno} is not valid JSON: {exc}"
            ) from None
        examples.append(_icl_example(item, f"{where} file {path} line {lineno}"))
    return examples


def build_icl(
    raw: Any, args: argparse.Namespace, prefix: str, config_dir: str
) -> IclConfig | None:
    """Parse the optional `icl` section. Returns None when ICL is not configured."""
    if raw is None:
        return None
    section = _require_mapping(raw, f"{prefix}.icl")
    if not section:
        return None

    setups_raw = section.get("setups")
    if setups_raw is None:
        raise ConfigError(f"config: '{prefix}.icl.setups' is required")
    if not isinstance(setups_raw, list):
        raise ConfigError(f"config: '{prefix}.icl.setups' must be a list")
    if not setups_raw:
        raise ConfigError(f"config: '{prefix}.icl.setups' must contain at least one setup")

    setups: list[IclSetup] = []
    for position, item in enumerate(setups_raw):
        where = f"'{prefix}.icl.setups[{position}]'"
        setup_raw = _require_mapping(item, f"{prefix}.icl.setups[{position}]")
        name = setup_raw.get("name")
        if name is None or str(name).strip() == "":
            raise ConfigError(f"config: {where} requires a non-empty 'name'")
        name = str(name)

        has_examples = setup_raw.get("examples") is not None
        has_file = setup_raw.get("file") is not None
        if has_examples == has_file:
            raise ConfigError(
                f"config: ICL setup {name!r} must have exactly one of 'examples' or 'file'"
            )

        if has_examples:
            items = setup_raw["examples"]
            if not isinstance(items, list):
                raise ConfigError(f"config: {where} 'examples' must be a list")
            examples = [
                _icl_example(entry, f"ICL setup {name!r} example {idx}")
                for idx, entry in enumerate(items)
            ]
        else:
            file_path = str(setup_raw["file"]).strip()
            if not file_path:
                raise ConfigError(f"config: {where} 'file' must be a non-empty path")
            if not os.path.isabs(file_path):
                file_path = os.path.join(config_dir, file_path)
            examples = load_icl_file(file_path, f"ICL setup {name!r}")

        setups.append(IclSetup(name=name, examples=examples))

    if getattr(args, "icl_strategy", None):
        strategy = str(args.icl_strategy).strip()
        strategy_label = "--icl-strategy"
    else:
        strategy = str(section.get("strategy", "fixed") or "fixed").strip()
        strategy_label = f"{prefix}.icl.strategy"
    if strategy not in ICL_STRATEGIES:
        raise ConfigError(
            f"config: '{strategy_label}' must be one of {', '.join(ICL_STRATEGIES)}, "
            f"got {strategy!r}"
        )

    if getattr(args, "icl_k", None) is not None:
        k = _as_int(args.icl_k, "--icl-k")
        k_label = "--icl-k"
    elif section.get("k") is not None:
        k = _as_int(section["k"], f"{prefix}.icl.k")
        k_label = f"{prefix}.icl.k"
    else:
        k = None
        k_label = f"{prefix}.icl.k"
    if k is not None and k < 0:
        raise ConfigError(f"config: '{k_label}' must be >= 0, got {k}")

    return IclConfig(setups=setups, strategy=strategy, k=k)


def build_icl_messages(icl: IclConfig, user_template: str, prefix: str) -> None:
    """Render each setup's examples into alternating user/assistant turns."""
    for setup in icl.setups:
        chosen = setup.examples if icl.k is None else setup.examples[: icl.k]
        messages: list[dict] = []
        for index, example in enumerate(chosen):
            try:
                content = user_template.format(**example.input)
            except KeyError as exc:
                missing = exc.args[0] if exc.args else "?"
                raise ConfigError(
                    f"config: '{prefix}.icl' setup {setup.name!r} example {index} is missing "
                    f"field {missing!r} referenced by {prefix}.prompt.user"
                ) from None
            except (IndexError, ValueError) as exc:
                raise ConfigError(
                    f"config: '{prefix}.icl' setup {setup.name!r} example {index}: {exc}"
                ) from None
            messages.append({"role": "user", "content": content})
            messages.append({"role": "assistant", "content": example.output})
        setup.messages = messages


def select_setup_index(config: Config, attempt: int, rng: "random.Random") -> int:
    """Which ICL setup a 0-based attempt uses, per `icl.strategy`."""
    icl = config.icl
    assert icl is not None
    count = len(icl.setups)
    if config.scheme == "greedy" and config.num_solutions > 1:
        # greedy walks setups in declared order, at most once each
        return min(attempt, count - 1)
    if icl.strategy == "fixed":
        return 0
    if icl.strategy == "random":
        return rng.randrange(count)
    return attempt % count


# --------------------------------------------------------------------------
# input
# --------------------------------------------------------------------------


def load_rows(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        raise ConfigError(f"input file not found: {path}") from None
    except IsADirectoryError:
        raise ConfigError(f"input file is a directory: {path}") from None
    except OSError as exc:
        raise ConfigError(f"could not read input file {path}: {exc}") from None

    rows: list[dict] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"input: row {len(rows)} (line {lineno}) is not valid JSON: {exc}")
        if not isinstance(row, dict):
            raise ConfigError(f"input: row {len(rows)} (line {lineno}) is not a JSON object")
        rows.append(row)
    return rows


def render_template(template: str, row: dict, index: int, what: str) -> str:
    try:
        return template.format(**row)
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "?"
        raise ConfigError(
            f"input: row {index} is missing field {missing!r} referenced by {what}"
        ) from None
    except (IndexError, ValueError) as exc:
        raise ConfigError(f"config: could not render {what}: {exc}") from None


def _require_fields(template: str, row: dict, index: int, what: str) -> None:
    """Check that every {placeholder} except __response__ exists in the row."""
    for name in template_fields(template, what):
        if name == RESPONSE_KEY:
            continue
        if name not in row:
            raise ConfigError(
                f"input: row {index} is missing field {name!r} referenced by {what}"
            )


@dataclass
class RowPrompt:
    """Rendered messages for one input row: the plain prompt plus one ICL variant per setup."""

    base: list[dict]
    variants: list[list[dict]] = field(default_factory=list)

    def messages(self, setup_index: int | None) -> list[dict]:
        if setup_index is None:
            return self.base
        return self.variants[setup_index]


def prepare_prompts(config: Config, rows: list[dict]) -> list[RowPrompt]:
    """Render every prompt up front so template/field errors surface before any request."""
    messages_per_row: list[RowPrompt] = []
    ev = config.evaluation
    answer_field = ev.answer_field if ev else None
    for index, row in enumerate(rows):
        prefix: list[dict] = []
        if config.system_template is not None:
            prefix.append(
                {
                    "role": "system",
                    "content": render_template(
                        config.system_template, row, index, "prompt.system"
                    ),
                }
            )
        user_message = {
            "role": "user",
            "content": render_template(config.user_template, row, index, "prompt.user"),
        }
        messages = prefix + [user_message]
        variants: list[list[dict]] = []
        if config.icl is not None:
            # ICL examples sit between the system message and the final user turn
            variants = [
                prefix + setup.messages + [user_message] for setup in config.icl.setups
            ]
        if answer_field and answer_field not in row:
            raise ConfigError(
                f"input: row {index} is missing field {answer_field!r} "
                f"required by evaluation.answer_field"
            )
        if ev is not None and ev.type == "script":
            _require_fields(ev.command_template, row, index, "evaluation.command_template")
        if ev is not None and ev.type == "llm_judge":
            _require_fields(ev.judge_user, row, index, "evaluation.judge_prompt.user")
            if ev.judge_system is not None:
                _require_fields(ev.judge_system, row, index, "evaluation.judge_prompt.system")
        messages_per_row.append(RowPrompt(base=messages, variants=variants))
    return messages_per_row


# --------------------------------------------------------------------------
# extraction + evaluation
# --------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d*\.\d+|-?\d+")
_LETTER_RE = re.compile(r"(?<![A-Za-z0-9])([A-D])(?![A-Za-z0-9])")


def extract_value(text: str, method: str) -> str | None:
    if text is None:
        return None
    if method == "full":
        return text.strip()
    if method == "last_line":
        for line in reversed(text.splitlines()):
            if line.strip():
                return line.strip()
        return ""
    if method == "last_number":
        matches = _NUMBER_RE.findall(text)
        if not matches:
            return None
        return matches[-1].replace(",", "")
    if method == "first_number":
        match = _NUMBER_RE.search(text)
        if match is None:
            return None
        return match.group(0).replace(",", "")
    if method == "letter":
        match = _LETTER_RE.search(text)
        if match is None:
            return None
        return match.group(1)
    return text.strip()


def _normalize(value: str) -> str:
    value = value.strip()
    value = value.replace(",", "").replace("$", "").replace("%", "")
    value = value.strip().rstrip(".")
    return value.strip()


def values_match(extracted: str | None, expected: Any) -> bool:
    if extracted is None or expected is None:
        return False
    expected_str = expected if isinstance(expected, str) else str(expected)
    if extracted.strip() == expected_str.strip():
        return True
    left, right = _normalize(extracted), _normalize(expected_str)
    if left == right:
        return True
    try:
        lnum, rnum = float(left), float(right)
    except (TypeError, ValueError):
        return False
    if math.isnan(lnum) or math.isnan(rnum):
        return False
    return math.isclose(lnum, rnum, rel_tol=1e-9, abs_tol=1e-9)


def parse_number(value: str | None) -> float | int | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


@dataclass
class EvalOutcome:
    passed: bool | None
    extracted: str | None = None
    judge_score: float | int | None = None
    judge_meta: dict | None = None


def evaluate_local(config: Config, text: str, row: dict) -> tuple[bool | None, str | None]:
    """exact_match / contains / regex: (passed, extracted_answer)."""
    ev = config.evaluation
    if ev is None:
        return None, None

    if ev.type == "regex":
        match = ev.regex.search(text) if ev.regex is not None else None
        if match is not None:
            extracted = match.group(1) if match.groups() else match.group(0)
            return True, extracted
        return False, extract_value(text, ev.extract)

    extracted = extract_value(text, ev.extract)
    expected = row.get(ev.answer_field) if ev.answer_field else None

    if ev.type == "contains":
        expected_str = "" if expected is None else str(expected)
        return (expected_str in text), extracted

    return values_match(extracted, expected), extracted


def render_command(ev: Evaluation, text: str, row: dict, index: int) -> str:
    """Render the shell command, substituting __response__ even inside row fields."""
    values = dict(row)
    values[RESPONSE_KEY] = text
    command = render_template(
        ev.command_template, values, index, "evaluation.command_template"
    )
    if RESPONSE_PLACEHOLDER in command:
        command = command.replace(RESPONSE_PLACEHOLDER, text)
    return command


async def run_script_eval(ev: Evaluation, text: str, row: dict, index: int) -> bool:
    try:
        command = render_command(ev, text, row, index)
    except ConfigError:
        return False

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group, so a timeout can kill grandchildren
        )
    except OSError:
        return False

    try:
        # stdout/stderr are captured but deliberately never written to the output
        await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT)
    except asyncio.TimeoutError:
        await _kill_process_group(proc)
        return False

    return proc.returncode == ev.success_exit_code


async def _kill_process_group(proc: Any) -> None:
    """Kill the command and anything it spawned; a lingering grandchild would
    otherwise hold the captured pipes open past the timeout."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except (asyncio.TimeoutError, ProcessLookupError, OSError):
        pass


async def run_judge_eval(
    client: httpx.AsyncClient,
    config: Config,
    text: str,
    row: dict,
    index: int,
    counter: "Counter",
) -> EvalOutcome:
    ev = config.evaluation
    values = dict(row)
    values[RESPONSE_KEY] = text

    try:
        messages: list[dict] = []
        if ev.judge_system is not None:
            messages.append(
                {
                    "role": "system",
                    "content": render_template(
                        ev.judge_system, values, index, "evaluation.judge_prompt.system"
                    ),
                }
            )
        messages.append(
            {
                "role": "user",
                "content": render_template(
                    ev.judge_user, values, index, "evaluation.judge_prompt.user"
                ),
            }
        )
    except ConfigError:
        return EvalOutcome(False, None, None, _empty_meta(ev.model or config.model, 0))

    result = await call_api(
        client,
        config.api_url,
        ev.model or config.model,
        messages,
        ev.judge_temperature,
        ev.judge_max_tokens or config.max_tokens,
        counter,
    )
    if not result.ok:
        return EvalOutcome(False, None, None, result.meta)

    extracted = extract_value(result.content, ev.extract)
    score = parse_number(extracted)
    if score is None:
        return EvalOutcome(False, extracted, None, result.meta)
    return EvalOutcome(score >= ev.threshold, extracted, score, result.meta)


async def evaluate_response(
    client: httpx.AsyncClient,
    config: Config,
    text: str,
    row: dict,
    index: int,
    counter: "Counter",
) -> EvalOutcome:
    ev = config.evaluation
    if ev is None:
        return EvalOutcome(None, None)
    if ev.type == "script":
        passed = await run_script_eval(ev, text, row, index)
        extracted = extract_value(text, ev.extract) if ev.extract_given else None
        return EvalOutcome(passed, extracted)
    if ev.type == "llm_judge":
        return await run_judge_eval(client, config, text, row, index, counter)
    passed, extracted = evaluate_local(config, text, row)
    return EvalOutcome(passed, extracted)


# --------------------------------------------------------------------------
# API client
# --------------------------------------------------------------------------


@dataclass
class CallResult:
    ok: bool
    content: str | None
    meta: dict
    api_calls: int
    error: str | None = None


class Counter:
    """Counts API calls; a per-task counter propagates to the global one."""

    def __init__(self, parent: "Counter | None" = None) -> None:
        self.parent = parent
        self.api_calls = 0
        self.first_request_at: float | None = None
        self.last_response_at: float | None = None

    def mark_request(self, at: float) -> None:
        self.api_calls += 1
        if self.first_request_at is None or at < self.first_request_at:
            self.first_request_at = at
        if self.parent is not None:
            self.parent.mark_request(at)

    def mark_response(self, at: float) -> None:
        if self.last_response_at is None or at > self.last_response_at:
            self.last_response_at = at
        if self.parent is not None:
            self.parent.mark_response(at)


def _empty_meta(model: str, latency_ms: int) -> dict:
    return {
        "model": model,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latency_ms": latency_ms,
        "finish_reason": None,
    }


async def call_api(
    client: httpx.AsyncClient,
    api_url: str,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    counter: Counter,
) -> CallResult:
    """One logical API call, retrying HTTP 5xx / transport failures."""
    url = f"{api_url}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    calls = 0
    last_error = "request failed"
    total_latency_ms = 0

    for attempt in range(MAX_RETRIES + 1):
        started = time.perf_counter()
        counter.mark_request(started)
        calls += 1
        try:
            response = await client.post(url, json=payload)
            elapsed = time.perf_counter() - started
            counter.mark_response(time.perf_counter())
            latency_ms = int(round(elapsed * 1000))
            total_latency_ms += latency_ms

            if response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
            elif response.status_code >= 400:
                return CallResult(
                    False,
                    None,
                    _empty_meta(model, latency_ms),
                    calls,
                    f"HTTP {response.status_code}",
                )
            else:
                try:
                    body = response.json()
                except ValueError as exc:
                    return CallResult(
                        False,
                        None,
                        _empty_meta(model, latency_ms),
                        calls,
                        f"invalid JSON response: {exc}",
                    )
                parsed = parse_completion(body, model, latency_ms)
                if parsed is None:
                    return CallResult(
                        False,
                        None,
                        _empty_meta(model, latency_ms),
                        calls,
                        "malformed completion response",
                    )
                content, meta = parsed
                return CallResult(True, content, meta, calls)
        except (httpx.HTTPError, OSError) as exc:
            elapsed = time.perf_counter() - started
            counter.mark_response(time.perf_counter())
            total_latency_ms += int(round(elapsed * 1000))
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < MAX_RETRIES:
            await asyncio.sleep(min(0.25 * (2**attempt), 2.0))

    return CallResult(False, None, _empty_meta(model, total_latency_ms), calls, last_error)


def parse_completion(body: Any, model: str, latency_ms: int) -> tuple[str, dict] | None:
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    message = choice.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        content = choice.get("text")
    if content is None:
        return None

    usage = body.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    def _tok(key: str) -> int:
        value = usage.get(key)
        return int(value) if isinstance(value, (int, float)) else 0

    meta = {
        "model": body.get("model") or model,
        "prompt_tokens": _tok("prompt_tokens"),
        "completion_tokens": _tok("completion_tokens"),
        "total_tokens": _tok("total_tokens"),
        "latency_ms": latency_ms,
        "finish_reason": choice.get("finish_reason"),
    }
    return str(content), meta


# --------------------------------------------------------------------------
# row processing
# --------------------------------------------------------------------------


async def process_row(
    client: httpx.AsyncClient,
    config: Config,
    row: dict,
    prompt: RowPrompt,
    counter: Counter,
    index: int,
) -> dict:
    """One input row -> one output record."""
    if config.list_format:
        return await process_row_multi(client, config, row, prompt, counter, index)
    return await process_row_single(client, config, row, prompt.base, counter, index)


async def process_row_single(
    client: httpx.AsyncClient,
    config: Config,
    row: dict,
    messages: list[dict],
    counter: Counter,
    index: int,
) -> dict:
    """Part 1/2 behaviour: one solution, object-shaped output and meta."""
    metas: list[dict] = []
    attempts = 0
    passed: bool | None = None
    extracted: str | None = None
    judge_score: float | int | None = None
    content: str | None = None

    is_judge = config.evaluation is not None and config.evaluation.type == "llm_judge"
    max_attempts = config.n if config.scheme == "rejection" else 1

    while attempts < max_attempts:
        attempts += 1
        result = await call_api(
            client,
            config.api_url,
            config.model,
            messages,
            config.temperature,
            config.max_tokens,
            counter,
        )
        metas.append(result.meta)
        if not result.ok:
            content = None
            passed = False if config.evaluation is not None else None
            extracted = None
            judge_score = None
            break

        outcome = await evaluate_response(client, config, result.content, row, index, counter)
        if outcome.judge_meta is not None:
            result.meta["judge_meta"] = outcome.judge_meta
        passed = outcome.passed
        extracted = outcome.extracted
        judge_score = outcome.judge_score
        content = result.content
        if config.scheme != "rejection" or passed:
            break
        # rejection: this attempt failed evaluation, drop it and try again
        content = None
        extracted = None
        judge_score = None

    if content is None and config.scheme == "rejection":
        passed = False
        extracted = None
        judge_score = None

    output = None if content is None else {config.output_field: content}
    meta_out: Any = metas[0] if len(metas) == 1 else metas
    if not metas:
        meta_out = None

    result_block: dict[str, Any] = {
        "passed": passed,
        "extracted_answer": extracted if output is not None else None,
        "attempts": attempts,
    }
    if is_judge:
        result_block["judge_score"] = judge_score if output is not None else None

    return {
        "input": row,
        "output": output,
        "result": result_block,
        "meta": meta_out,
    }


def _attempt_budget(config: Config) -> int:
    """How many generation attempts a row may make at most."""
    if config.scheme == "greedy":
        if config.icl is not None and config.num_solutions > 1:
            # one deterministic shot per setup: at most one solution each
            return len(config.icl.setups)
        return 1
    if config.scheme == "sample":
        return config.num_solutions
    return config.max_attempts or (3 * config.num_solutions)


async def process_row_multi(
    client: httpx.AsyncClient,
    config: Config,
    row: dict,
    prompt: RowPrompt,
    counter: Counter,
    index: int,
) -> dict:
    """Part 3 behaviour: a list of solutions, one meta entry per attempt."""
    rng = random.Random()
    has_eval = config.evaluation is not None
    budget = _attempt_budget(config)
    gated = config.scheme == "rejection"  # only rejection drops failing generations

    metas: list[dict] = []
    outputs: list[dict] = []
    attempts = 0
    passed_count = 0

    while attempts < budget:
        if gated:
            if passed_count >= config.num_solutions:
                break
        elif len(outputs) >= config.num_solutions:
            break

        setup_index = None if config.icl is None else select_setup_index(config, attempts, rng)
        setup_name = None if setup_index is None else config.icl.setups[setup_index].name
        attempts += 1

        result = await call_api(
            client,
            config.api_url,
            config.model,
            prompt.messages(setup_index),
            config.temperature,
            config.max_tokens,
            counter,
        )
        meta = result.meta
        if not result.ok:
            meta["icl_setup"] = setup_name
            meta["evaluation_passed"] = False if has_eval else None
            metas.append(meta)
            continue

        outcome = await evaluate_response(client, config, result.content, row, index, counter)
        if outcome.judge_meta is not None:
            meta["judge_meta"] = outcome.judge_meta
        meta["icl_setup"] = setup_name
        meta["evaluation_passed"] = outcome.passed
        metas.append(meta)

        if outcome.passed:
            passed_count += 1
        if not gated or outcome.passed:
            outputs.append({config.output_field: result.content, "icl_setup": setup_name})

    passed = passed_count if has_eval else len(outputs)
    return {
        "input": row,
        "output": outputs,
        "result": {
            "passed": passed,
            "failed": attempts - passed,
            "attempts": attempts,
        },
        "meta": metas,
    }


def choose_concurrency(config: Config, row_count: int) -> int:
    if row_count <= 0:
        return 1
    limit = max(8, min(config.rpm, 256))
    return max(1, min(limit, row_count))


@dataclass
class TaskRun:
    config: Config
    rows: list[dict]
    prompts: list[RowPrompt]
    output_path: str
    counter: Counter = field(default_factory=Counter)
    results: list[dict] = field(default_factory=list)


async def run_tasks(runs: list[TaskRun]) -> Counter:
    """Run every task concurrently over one shared connection pool."""
    global_counter = Counter()
    active = [run for run in runs if run.rows]
    for run in runs:
        run.counter = Counter(parent=global_counter)
        run.results = []
    if not active:
        return global_counter

    sizes = {id(run): choose_concurrency(run.config, len(run.rows)) for run in active}
    pool = min(sum(sizes.values()), 1024)
    limits = httpx.Limits(max_connections=pool + 8, max_keepalive_connections=pool + 8)
    timeout = httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=600.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        coros = []
        for run in active:
            concurrency = sizes[id(run)]
            semaphore = asyncio.Semaphore(concurrency)
            slots: list[dict | None] = [None] * len(run.rows)
            run.results = slots  # type: ignore[assignment]

            # Gentle ramp: avoids a thundering herd of simultaneous connects on
            # servers with a small listen backlog, without pacing below capacity.
            ramp = min(0.004, 0.25 / concurrency) if concurrency > 1 else 0.0

            def make_worker(run: TaskRun, semaphore, slots, concurrency, ramp):
                async def worker(index: int) -> None:
                    if index < concurrency and ramp:
                        await asyncio.sleep(index * ramp)
                    async with semaphore:
                        slots[index] = await process_row(
                            client,
                            run.config,
                            run.rows[index],
                            run.prompts[index],
                            run.counter,
                            index,
                        )

                return worker

            worker = make_worker(run, semaphore, slots, concurrency, ramp)
            coros.extend(worker(i) for i in range(len(run.rows)))

        await asyncio.gather(*coros)

    for run in runs:
        run.results = [record for record in run.results if record is not None]

    return global_counter


# --------------------------------------------------------------------------
# summary + output
# --------------------------------------------------------------------------


def _tally(results: list[dict]) -> tuple[int, int, int, int, int]:
    """(rows passed, rows failed, prompt tokens, completion tokens, solutions)."""
    passed = failed = prompt_tokens = completion_tokens = solutions = 0
    for record in results:
        metas = record["meta"]
        if isinstance(metas, dict):
            metas = [metas]
        elif metas is None:
            metas = []
        for meta in metas:
            prompt_tokens += meta.get("prompt_tokens") or 0
            completion_tokens += meta.get("completion_tokens") or 0
            judge_meta = meta.get("judge_meta")
            if isinstance(judge_meta, dict):
                prompt_tokens += judge_meta.get("prompt_tokens") or 0
                completion_tokens += judge_meta.get("completion_tokens") or 0

        row_passed = record["result"]["passed"]
        output = record["output"]
        if isinstance(output, list):
            # part 3 list format: the row passes when it yielded a passing solution
            solutions += len(output)
            row_ok = isinstance(row_passed, int) and row_passed >= 1
        else:
            has_output = output is not None
            solutions += 1 if has_output else 0
            row_ok = row_passed is True or (row_passed is None and has_output)
        if row_ok:
            passed += 1
        else:
            failed += 1
    return passed, failed, prompt_tokens, completion_tokens, solutions


def _avg(solutions: int, rows: int) -> float:
    return round(solutions / rows, 2) if rows else 0.0


def build_summary(runs: list[TaskRun], counter: Counter, multi: bool) -> dict:
    total = passed = failed = prompt_tokens = completion_tokens = solutions = 0
    per_task: dict[str, dict] = {}
    any_multi = any(run.config.list_format for run in runs)

    for run in runs:
        t_passed, t_failed, t_prompt, t_completion, t_solutions = _tally(run.results)
        total += len(run.results)
        passed += t_passed
        failed += t_failed
        prompt_tokens += t_prompt
        completion_tokens += t_completion
        solutions += t_solutions
        per_task[run.config.name] = {
            "total": len(run.results),
            "passed": t_passed,
            "failed": t_failed,
            "total_solutions": t_solutions,
            "avg_solutions_per_input": _avg(t_solutions, len(run.results)),
            "total_api_calls": run.counter.api_calls,
        }

    if counter.first_request_at is not None and counter.last_response_at is not None:
        elapsed = max(0.0, counter.last_response_at - counter.first_request_at)
    else:
        elapsed = 0.0

    throughput = (counter.api_calls / elapsed * 60.0) if elapsed > 0 else 0.0

    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "total_prompt_tokens": prompt_tokens,
        "total_completion_tokens": completion_tokens,
        "total_api_calls": counter.api_calls,
        "elapsed_seconds": round(elapsed, 1),
        "throughput_rpm": round(throughput, 1),
    }
    if any_multi:
        # only meaningful once a run can emit several solutions per input
        summary["total_solutions"] = solutions
        summary["avg_solutions_per_input"] = _avg(solutions, total)
    if multi:
        summary["tasks"] = per_task
    return summary


def write_results(path: str, results: list[dict]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as handle:
            for record in results:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ConfigError(f"could not write output file {path}: {exc}") from None


# --------------------------------------------------------------------------
# planning (config + CLI -> task runs)
# --------------------------------------------------------------------------


@dataclass
class Plan:
    runs: list[TaskRun]
    multi: bool


def _selected_names(args: argparse.Namespace, available: list[str]) -> list[str]:
    if not args.task:
        return list(available)
    selected: list[str] = []
    for name in args.task:
        name = str(name).strip()
        if name not in available:
            raise ConfigError(
                f"--task {name!r} is not defined in the config "
                f"(available: {', '.join(available)})"
            )
        if name not in selected:
            selected.append(name)
    return selected


def _resolve_output_dir(path: str) -> str:
    if os.path.exists(path) and not os.path.isdir(path):
        raise ConfigError(f"--output must be a directory for multi-task configs: {path}")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"could not create output directory {path}: {exc}") from None
    return path


def _multi_inputs(args: argparse.Namespace, available: list[str], selected: list[str]) -> dict:
    if args.input and args.input_dir:
        raise ConfigError(
            "--input and --input-dir are alternative modes; pass one or the other"
        )

    mapping: dict[str, str] = {}
    if args.input:
        for item in args.input:
            if "=" not in item:
                raise ConfigError(
                    f"--input must be given as <task>=<path> for multi-task configs, got {item!r}"
                )
            name, path = item.split("=", 1)
            name = name.strip()
            if name not in available:
                raise ConfigError(
                    f"--input refers to unknown task {name!r} "
                    f"(available: {', '.join(available)})"
                )
            if path.strip() == "":
                raise ConfigError(f"--input for task {name!r} has an empty path")
            mapping[name] = path
    elif args.input_dir:
        if not os.path.isdir(args.input_dir):
            raise ConfigError(f"input directory not found: {args.input_dir}")
        for name in selected:
            mapping[name] = os.path.join(args.input_dir, f"{name}.jsonl")
    else:
        raise ConfigError("one of --input <task=path> or --input-dir is required")

    resolved: dict[str, str] = {}
    for name in selected:
        path = mapping.get(name)
        if path is None:
            raise ConfigError(f"no input file given for task {name!r} (use --input {name}=<path>)")
        if not os.path.exists(path):
            raise ConfigError(f"input file not found for task {name!r}: {path}")
        resolved[name] = path
    return resolved


def _single_input(args: argparse.Namespace, name: str) -> str:
    if args.input and args.input_dir:
        raise ConfigError(
            "--input and --input-dir are alternative modes; pass one or the other"
        )
    if args.input:
        if len(args.input) > 1:
            raise ConfigError("--input may only be given once for single-task configs")
        item = args.input[0]
        if "=" in item:
            prefix, rest = item.split("=", 1)
            if prefix.strip() == name:
                return rest
        return item
    if args.input_dir:
        if not os.path.isdir(args.input_dir):
            raise ConfigError(f"input directory not found: {args.input_dir}")
        path = os.path.join(args.input_dir, f"{name}.jsonl")
        if not os.path.exists(path):
            raise ConfigError(f"input file not found for task {name!r}: {path}")
        return path
    raise ConfigError("--input is required")


def build_plan(raw: dict, args: argparse.Namespace) -> Plan:
    config_dir = os.path.dirname(os.path.abspath(args.config)) or "."
    if is_multi_config(raw):
        defaults = _require_mapping(raw.get("defaults") or {}, "defaults")
        tasks = _require_mapping(raw.get("tasks"), "tasks")
        if not tasks:
            raise ConfigError("config: 'tasks' must contain at least one task")

        available = [str(key) for key in tasks]
        selected = _selected_names(args, available)
        if not selected:
            raise ConfigError("config: no tasks selected")

        # configs first, so a broken task is reported before any path juggling
        configs: dict[str, Config] = {}
        for name in selected:
            body = _require_mapping(tasks[name] or {}, f"tasks.{name}")
            configs[name] = build_config(
                deep_merge(defaults, body), args, name, f"tasks.{name}", config_dir
            )

        inputs = _multi_inputs(args, available, selected)
        output_dir = _resolve_output_dir(args.output)

        runs: list[TaskRun] = []
        for name in selected:
            config = configs[name]
            rows = load_rows(inputs[name])
            try:
                prompts = prepare_prompts(config, rows)
            except ConfigError as exc:
                raise ConfigError(f"task {name!r}: {exc}") from None
            runs.append(
                TaskRun(
                    config=config,
                    rows=rows,
                    prompts=prompts,
                    output_path=os.path.join(output_dir, f"{name}.jsonl"),
                )
            )
        return Plan(runs=runs, multi=True)

    if "task" not in raw:
        raise ConfigError("config: missing required section 'task'")
    task = _require_mapping(raw["task"], "task")
    name = str(task.get("name", "task"))
    _selected_names(args, [name])
    config = build_config(task, args, name, "task", config_dir)
    rows = load_rows(_single_input(args, name))
    prompts = prepare_prompts(config, rows)
    return Plan(
        runs=[TaskRun(config=config, rows=rows, prompts=prompts, output_path=args.output)],
        multi=False,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # noqa: D102 - argparse hook
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="rejector.py", description="Run generation tasks against an OpenAI-compatible API."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one or more tasks over JSONL input")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument(
        "--input",
        action="append",
        default=None,
        help="JSONL input file, or <task>=<path> for multi-task configs (repeatable)",
    )
    run.add_argument(
        "--input-dir",
        dest="input_dir",
        default=None,
        help="directory holding <task_name>.jsonl for each task",
    )
    run.add_argument("--output", required=True, help="JSONL output file, or directory for multi-task")
    run.add_argument("--task", action="append", default=None, help="run only this task (repeatable)")
    run.add_argument("--api-url", dest="api_url", default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--eval-model", dest="eval_model", default=None, help="override llm_judge model")
    run.add_argument("--rpm", type=int, default=None)
    run.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    run.add_argument("--scheme", choices=list(SCHEMES), default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--n", type=int, default=None)
    run.add_argument(
        "--num-solutions",
        dest="num_solutions",
        type=int,
        default=None,
        help="number of solutions to collect per input",
    )
    run.add_argument(
        "--icl-strategy",
        dest="icl_strategy",
        choices=list(ICL_STRATEGIES),
        default=None,
        help="how ICL setups are chosen across attempts",
    )
    run.add_argument(
        "--icl-k",
        dest="icl_k",
        type=int,
        default=None,
        help="number of ICL examples to use from the selected setup",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        raw = load_config(args.config)
        plan = build_plan(raw, args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        counter = asyncio.run(run_tasks(plan.runs))
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return EXIT_ERROR

    try:
        for run in plan.runs:
            write_results(run.output_path, run.results)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(json.dumps(build_summary(plan.runs, counter, plan.multi)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
