"""In-context learning setups: loading them, and picking one per attempt."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from rejlib.errors import ConfigError
from rejlib.validate import mapping, positive_int, required_text

STRATEGIES = ("fixed", "random", "round_robin")
DEFAULT_STRATEGY = "fixed"


@dataclass(frozen=True)
class Example:
    """One demonstration: the row it renders from and the assistant reply it shows."""

    input: dict
    output: str


@dataclass(frozen=True)
class Setup:
    """A named list of demonstrations."""

    name: str
    examples: tuple[Example, ...]


@dataclass(frozen=True)
class IclConfig:
    """A task's ICL setups, how many examples to show, and how a setup is picked."""

    setups: tuple[Setup, ...]
    strategy: str = DEFAULT_STRATEGY
    #: Examples to show per setup; ``None`` means every example the setup has.
    k: int | None = None

    def examples(self, setup: Setup) -> tuple[Example, ...]:
        """``setup``'s demonstrations, truncated to the first ``k`` (T44)."""
        return setup.examples if self.k is None else setup.examples[: self.k]

    def select(self, attempt: int) -> Setup:
        """The setup that attempt number ``attempt`` (0-based) uses."""
        if self.strategy == "random":
            return random.choice(self.setups)
        if self.strategy == "round_robin":
            return self.setups[attempt % len(self.setups)]
        return self.setups[0]


def load_icl(raw, base_dir: Path, label: str, provided: dict) -> IclConfig | None:
    """Build the ICL config of one task, or ``None`` when it configures none.

    ``base_dir`` is the config file's directory, which file-backed setups resolve
    their paths against. ``provided`` carries the ``--icl-k`` and
    ``--icl-strategy`` overrides; neither creates ICL for a task without setups
    (T55).
    """
    if raw is None:
        return None
    body = mapping(raw, label)
    setups = body.get("setups")
    if not isinstance(setups, list) or not setups:
        raise ConfigError(f"{label}.setups must be a non-empty list of setups")

    k = provided.get("icl_k", body.get("k"))
    return IclConfig(
        setups=tuple(
            _setup(entry, base_dir, f"{label}.setups[{index}]")
            for index, entry in enumerate(setups)
        ),
        strategy=_strategy(provided.get("icl_strategy", body.get("strategy")), label),
        k=None if k is None else positive_int(f"{label}.k", k),
    )


def _strategy(value, label: str) -> str:
    """The selection strategy; omitting it means `fixed` (T39)."""
    if value is None:
        return DEFAULT_STRATEGY
    if value not in STRATEGIES:
        raise ConfigError(
            f"{label}.strategy must be one of {', '.join(STRATEGIES)}, got {value!r}"
        )
    return value


def _setup(raw, base_dir: Path, label: str) -> Setup:
    """One setup: inline examples or a JSONL file, never both and never neither."""
    body = mapping(raw, label)
    name = required_text(body, "name", f"{label}.name")
    if ("examples" in body) == ("file" in body):
        raise ConfigError(f"{label} must have exactly one of 'examples' or 'file'")

    if "file" in body:
        path = base_dir / required_text(body, "file", f"{label}.file")
        return Setup(name, tuple(_file_examples(path)))
    inline = body["examples"]
    if not isinstance(inline, list):
        raise ConfigError(f"{label}.examples must be a list")
    return Setup(
        name,
        tuple(
            _example(entry, f"{label}.examples[{index}]")
            for index, entry in enumerate(inline)
        ),
    )


def _file_examples(path: Path) -> list[Example]:
    """Parse a JSONL example file; blank lines are skipped like the input file."""
    try:
        text = path.read_text()
    except OSError as exc:
        raise ConfigError(f"cannot read ICL examples {path}: {exc}") from exc

    examples = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} line {number} is not valid JSON: {exc}") from exc
        examples.append(_example(entry, f"{path} line {number}"))
    return examples


def _example(entry, label: str) -> Example:
    """One demonstration: an ``input`` object and an ``output`` string."""
    if not isinstance(entry, dict):
        raise ConfigError(f"{label} must be a JSON object")
    if not isinstance(entry.get("input"), dict) or not isinstance(entry.get("output"), str):
        raise ConfigError(
            f"{label} must have an 'input' object and an 'output' string"
        )
    return Example(entry["input"], entry["output"])
