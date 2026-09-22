"""In-context learning setups: declaration, example loading, and selection.

A setup is a named list of demonstrations replayed ahead of the row's own
question.  Setups are declared inline in the config or loaded from a JSONL
file resolved against the config's directory, and one setup is chosen per
generation attempt by the configured strategy.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import cycle, repeat
from pathlib import Path

from .errors import ConfigError

STRATEGIES = ("fixed", "random", "round_robin")
DEFAULT_STRATEGY = "fixed"


@dataclass(frozen=True)
class IclExample:
    """One demonstration: the row fields to render, and the answer to replay."""

    input: dict
    output: str


@dataclass(frozen=True)
class IclSetup:
    """A named list of demonstrations."""

    name: str
    examples: tuple[IclExample, ...]


@dataclass(frozen=True)
class IclConfig:
    """Every setup a task declares, plus how many examples to use and which."""

    setups: tuple[IclSetup, ...]
    strategy: str
    k: int | None = None

    def examples_of(self, setup: IclSetup) -> tuple[IclExample, ...]:
        """One setup's examples, truncated to the first `k` when `k` is set."""
        return setup.examples if self.k is None else setup.examples[: self.k]


def build_icl(icl, config_dir: Path, label: str) -> IclConfig | None:
    """Validate a task's `icl` section, loading any file-backed setups."""
    if icl is None:
        return None
    if not isinstance(icl, dict):
        raise ConfigError(f"{label} must be a mapping")

    setups = icl.get("setups")
    if not isinstance(setups, list) or not setups:
        raise ConfigError(f"{label}.setups must be a non-empty list")

    strategy = icl.get("strategy", DEFAULT_STRATEGY)
    if strategy not in STRATEGIES:
        raise ConfigError(
            f"unknown icl strategy '{strategy}'; expected one of {', '.join(STRATEGIES)}"
        )

    k = icl.get("k")
    if k is not None and (isinstance(k, bool) or not isinstance(k, int) or k < 1):
        raise ConfigError(f"{label}.k must be a positive integer")

    built = tuple(
        _build_setup(setup, config_dir, f"{label}.setups[{index}]")
        for index, setup in enumerate(setups)
    )
    return IclConfig(setups=built, strategy=strategy, k=k)


def check_examples(icl: IclConfig, fields: list[str], label: str) -> None:
    """Fail when an example's input lacks a field the user template renders."""
    for setup in icl.setups:
        for index, example in enumerate(setup.examples):
            missing = [field for field in fields if field not in example.input]
            if missing:
                raise ConfigError(
                    f"{label} setup '{setup.name}' example {index} is missing field '{missing[0]}'"
                )


def setup_sequence(icl: IclConfig | None, declared_order: bool) -> Iterator[IclSetup | None]:
    """The setup to use for each successive attempt of one row.

    `declared_order` walks the setups once each, which is how greedy decoding
    produces distinct solutions.  Otherwise the configured strategy decides,
    starting afresh for every row so that a row's prompts do not depend on the
    order in which rows happen to finish.
    """
    if icl is None:
        return repeat(None)
    if declared_order:
        return iter(icl.setups)
    if icl.strategy == "random":
        return _random_setups(icl.setups)
    if icl.strategy == "round_robin":
        return cycle(icl.setups)
    return repeat(icl.setups[0])


def _random_setups(setups: tuple[IclSetup, ...]) -> Iterator[IclSetup]:
    while True:
        yield random.choice(setups)


def _build_setup(setup, config_dir: Path, label: str) -> IclSetup:
    if not isinstance(setup, dict):
        raise ConfigError(f"{label} must be a mapping")
    name = setup.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{label}.name is required")

    inline, file = setup.get("examples"), setup.get("file")
    if (inline is None) == (file is None):
        raise ConfigError(f"{label} needs exactly one of 'examples' or 'file'")
    if inline is None and not isinstance(file, str):
        raise ConfigError(f"{label}.file must be a string")

    examples = _inline_examples(inline, label) if file is None else _file_examples(config_dir / file, label)
    if not examples:
        raise ConfigError(f"{label} declares no examples")
    return IclSetup(name=name, examples=examples)


def _inline_examples(examples, label: str) -> tuple[IclExample, ...]:
    if not isinstance(examples, list):
        raise ConfigError(f"{label}.examples must be a list")
    return tuple(
        _example(entry, f"{label}.examples[{index}]") for index, entry in enumerate(examples)
    )


def _file_examples(path: Path, label: str) -> tuple[IclExample, ...]:
    """Read a JSONL example file; one malformed line fails the whole run."""
    if not path.is_file():
        raise ConfigError(f"{label}.file not found: {path}")

    examples = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{label}.file line {number} is not valid JSON: {exc.msg}") from exc
        examples.append(_example(entry, f"{label}.file line {number}"))
    return tuple(examples)


def _example(entry, label: str) -> IclExample:
    """One `{"input": <object>, "output": <string>}` demonstration."""
    if not isinstance(entry, dict):
        raise ConfigError(f"{label} must be a mapping")
    if not isinstance(entry.get("input"), dict):
        raise ConfigError(f"{label}.input must be an object")
    if not isinstance(entry.get("output"), str):
        raise ConfigError(f"{label}.output must be a string")
    return IclExample(input=entry["input"], output=entry["output"])
