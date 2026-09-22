"""In-context learning setups: their examples and how attempts choose between them.

A setup is a named list of demonstrations. Each example's input is rendered
through the task's own user template, so a setup produces the same alternating
user/assistant turns for every row of the task; `prepare_plan` renders them once
and `IclPlan.choose` picks the setup an individual attempt prompts with.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from errors import ConfigError
from prompts import render, template_fields

STRATEGIES = ("fixed", "random", "round_robin")
DEFAULT_STRATEGY = "fixed"


@dataclass(frozen=True)
class IclExample:
    """One demonstration: the row it is rendered from, and the answer to show."""

    input: dict[str, Any]
    output: str


@dataclass(frozen=True)
class IclSetup:
    """A named list of demonstrations, declared inline or read from a file."""

    name: str
    examples: tuple[IclExample, ...]


@dataclass(frozen=True)
class IclConfig:
    """The setups a task may prompt with, how many examples to show, and which to pick."""

    setups: tuple[IclSetup, ...]
    strategy: str
    k: int | None = None


@dataclass(frozen=True)
class PreparedSetup:
    """A setup's examples rendered into the turns every request repeats."""

    name: str
    turns: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class IclPlan:
    """The prepared setups of one task; empty when the task configures no ICL."""

    setups: tuple[PreparedSetup, ...] = ()
    strategy: str = DEFAULT_STRATEGY

    def choose(self, attempt_index: int) -> PreparedSetup | None:
        """The setup for one attempt of a row, or None when there is no ICL."""
        if not self.setups:
            return None
        if self.strategy == "random":
            return random.choice(self.setups)
        if self.strategy == "round_robin":
            return self.setups[attempt_index % len(self.setups)]
        return self.setups[0]


def load_examples(path: Path, where: str) -> tuple[IclExample, ...]:
    """Read a JSONL example file, one `{"input": ..., "output": ...}` per line.

    Raises:
        ConfigError: the file is unreadable, empty, or holds a malformed line.
    """
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise ConfigError(f"{where}: cannot read {path}: {exc}") from exc

    examples = [
        _parse_example(line, f"{where}: {path} line {number}")
        for number, line in enumerate(lines, start=1)
        if line.strip()
    ]
    if not examples:
        raise ConfigError(f"{where}: {path} contains no examples")
    return tuple(examples)


def prepare_plan(config: IclConfig | None, user_template: str) -> IclPlan:
    """Render every setup's examples through the task's user template.

    Raises:
        ConfigError: an example's input lacks a field the template needs, so a
            broken setup stops the run before any request is sent.
    """
    if config is None:
        return IclPlan()
    return IclPlan(
        setups=tuple(_prepare_setup(setup, config.k, user_template) for setup in config.setups),
        strategy=config.strategy,
    )


def _parse_example(line: str, where: str) -> IclExample:
    try:
        entry = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{where}: invalid JSON: {exc}") from exc
    if not isinstance(entry, dict):
        raise ConfigError(f"{where}: expected a JSON object")
    if not isinstance(entry.get("input"), dict) or not isinstance(entry.get("output"), str):
        raise ConfigError(f"{where}: expected an object 'input' and a string 'output'")
    return IclExample(input=entry["input"], output=entry["output"])


def _prepare_setup(setup: IclSetup, k: int | None, user_template: str) -> PreparedSetup:
    """Take the first `k` examples of a setup, or all of them when `k` is unset."""
    return PreparedSetup(
        name=setup.name,
        turns=tuple(
            (_render_input(example.input, setup.name, user_template), example.output)
            for example in setup.examples[:k]
        ),
    )


def _render_input(values: dict[str, Any], name: str, user_template: str) -> str:
    missing = sorted(template_fields(user_template) - values.keys())
    if missing:
        raise ConfigError(
            f"icl setup '{name}': an example is missing field '{missing[0]}' "
            "required by the prompt template"
        )
    return render(user_template, values)
