"""In-context learning: setup configuration, example loading, and per-attempt selection.

A setup is a named list of input/output examples, either written inline in the
config or read from a JSONL file next to it. The examples are rendered once per
setup into alternating user/assistant turns that every row's prompt reuses.
"""

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from errors import ConfigError
from templates import render_template

STRATEGIES = ("fixed", "random", "round_robin")
DEFAULT_STRATEGY = "fixed"


@dataclass(frozen=True)
class IclExample:
    """One demonstration: the row fields its prompt is rendered from, and the reply to show."""

    input: dict[str, Any]
    output: str


@dataclass(frozen=True)
class IclSetup:
    """A named list of demonstrations that can be prepended to a task's prompt."""

    name: str
    examples: tuple[IclExample, ...]


@dataclass(frozen=True)
class IclConfig:
    """Every setup a task defines, how many examples to show, and how to pick a setup."""

    setups: tuple[IclSetup, ...]
    k: int | None
    strategy: str


@dataclass(frozen=True)
class RenderedSetup:
    """A setup's example turns, ready to splice into a row's messages.

    ``name`` is ``None`` for the single placeholder setup of a task without ICL.
    """

    name: str | None
    messages: list[dict[str, str]]


#: The lone setup used when a task has no ICL: no extra turns, no setup name.
NO_ICL: tuple[RenderedSetup, ...] = (RenderedSetup(name=None, messages=[]),)


def build_icl(raw: Any, config_dir: Path, label: str) -> IclConfig | None:
    """Validate the optional ``icl`` block, reading file-backed setups from ``config_dir``."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{label}.icl must be a mapping")

    setups = raw.get("setups")
    if not isinstance(setups, list) or not setups:
        raise ConfigError(f"{label}.icl.setups must be a non-empty list")
    strategy = raw.get("strategy", DEFAULT_STRATEGY)
    if strategy not in STRATEGIES:
        raise ConfigError(f"{label}.icl.strategy must be one of: {', '.join(STRATEGIES)}")

    k = raw.get("k")
    if k is not None and (not isinstance(k, int) or k <= 0):
        raise ConfigError(f"{label}.icl.k must be a positive integer")
    built = tuple(
        _build_setup(setup, config_dir, f"{label}.icl.setups[{index}]")
        for index, setup in enumerate(setups)
    )
    return IclConfig(setups=built, k=k, strategy=strategy)


def render_setups(icl: IclConfig | None, user_template: str) -> tuple[RenderedSetup, ...]:
    """Render each setup's examples into the turns every row's prompt will reuse."""
    if icl is None:
        return NO_ICL
    return tuple(
        RenderedSetup(setup.name, _example_turns(setup, icl.k, user_template))
        for setup in icl.setups
    )


def build_messages(base: list[dict[str, str]], setup: RenderedSetup) -> list[dict[str, str]]:
    """Splice a setup's example turns between the system message and the row's user message."""
    return base[:-1] + setup.messages + base[-1:]


def setup_for_attempt(
    setups: tuple[RenderedSetup, ...], strategy: str, attempt: int
) -> RenderedSetup:
    """Pick the setup for a zero-based attempt number according to ``strategy``."""
    if strategy == "random":
        return random.choice(setups)
    if strategy == "round_robin":
        return setups[attempt % len(setups)]
    return setups[0]


def _example_turns(setup: IclSetup, k: int | None, user_template: str) -> list[dict[str, str]]:
    """Turn the first ``k`` examples of one setup into alternating user/assistant messages."""
    turns = []
    for index, example in enumerate(setup.examples[:k]):
        context = f"icl setup '{setup.name}' example {index}"
        turns.append({"role": "user", "content": render_template(user_template, example.input, context)})
        turns.append({"role": "assistant", "content": example.output})
    return turns


def _build_setup(raw: Any, config_dir: Path, label: str) -> IclSetup:
    """Validate one setup, which carries its examples either inline or in a JSONL file."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} must be a mapping")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{label}.name must be a non-empty string")

    inline, path = raw.get("examples"), raw.get("file")
    if (inline is None) == (path is None):
        raise ConfigError(f"{label} must define exactly one of 'examples' or 'file'")
    if path is not None:
        return IclSetup(name, _read_examples(config_dir, path, label))
    if not isinstance(inline, list) or not inline:
        raise ConfigError(f"{label}.examples must be a non-empty list")
    return IclSetup(
        name,
        tuple(_build_example(example, f"{label}.examples[{index}]") for index, example in enumerate(inline)),
    )


def _read_examples(config_dir: Path, path: Any, label: str) -> tuple[IclExample, ...]:
    """Read a setup's examples from a JSONL file resolved against the config's directory."""
    if not isinstance(path, str) or not path.strip():
        raise ConfigError(f"{label}.file must be a non-empty string")
    resolved = config_dir / path
    try:
        lines = resolved.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"{label}.file: cannot read {resolved}: {exc}") from exc

    examples = []
    for number, line in enumerate(lines, start=1):
        if line.strip():
            examples.append(_parse_line(resolved, number, line))
    if not examples:
        raise ConfigError(f"{label}.file: {resolved} has no examples")
    return tuple(examples)


def _parse_line(path: Path, number: int, line: str) -> IclExample:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: line {number} is not valid JSON: {exc.msg}") from exc
    return _build_example(payload, f"{path} line {number}")


def _build_example(raw: Any, label: str) -> IclExample:
    """Validate one ``{"input": {...}, "output": "..."}`` example."""
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{label}: must be a mapping with 'input' and 'output'")
    example_input, output = raw.get("input"), raw.get("output")
    if not isinstance(example_input, dict):
        raise ConfigError(f"{label}: 'input' must be a mapping of template fields")
    if not isinstance(output, str):
        raise ConfigError(f"{label}: 'output' must be a string")
    return IclExample(input=example_input, output=output)
