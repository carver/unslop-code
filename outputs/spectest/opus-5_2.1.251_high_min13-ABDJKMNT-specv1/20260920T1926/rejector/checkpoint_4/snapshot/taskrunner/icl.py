"""In-context learning setups: their configuration and per-attempt selection.

A setup is a named list of demonstrations, given inline or in a JSONL file
beside the config. Which setup an attempt uses is decided by the configured
strategy, except for greedy multi-solution runs, which walk the setups in
declared order instead.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import ConfigError

STRATEGIES = ("fixed", "random", "round_robin")
DEFAULT_STRATEGY = "fixed"

# Internal strategy for greedy multi-solution runs: one attempt per setup, in
# declaration order, so the same deterministic prompt is never repeated.
DECLARED_ORDER = "declared_order"


@dataclass(frozen=True)
class IclExample:
    """One demonstration: a row-shaped input and the reply to show for it."""

    input: dict[str, Any]
    output: str


@dataclass(frozen=True)
class IclSetup:
    name: str
    examples: tuple[IclExample, ...]


@dataclass(frozen=True)
class IclConfig:
    setups: tuple[IclSetup, ...]
    k: int | None
    strategy: str


def build_icl(
    raw: Any, overrides: Mapping[str, Any], base_dir: Path, where: str
) -> IclConfig | None:
    """Validate a task's `icl` section; `base_dir` holds the config file."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where}.icl must be a mapping")

    setups = raw.get("setups")
    if not isinstance(setups, list) or not setups:
        raise ConfigError(f"{where}.icl.setups must be a non-empty list of setups")

    strategy = overrides.get("icl_strategy") or raw.get("strategy", DEFAULT_STRATEGY)
    if strategy not in STRATEGIES:
        raise ConfigError(
            f"{where}.icl.strategy must be one of {', '.join(STRATEGIES)}, got '{strategy}'"
        )
    return IclConfig(
        setups=tuple(
            _build_setup(setup, base_dir, f"{where}.icl.setups[{index}]")
            for index, setup in enumerate(setups)
        ),
        k=_k(overrides.get("icl_k", raw.get("k")), f"{where}.icl.k"),
        strategy=strategy,
    )


def _k(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{label} must be an integer >= 1, got {value!r}")
    return value


def _build_setup(raw: Any, base_dir: Path, where: str) -> IclSetup:
    """One named setup, with demonstrations from `examples` or from `file`."""
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where} must be a mapping")
    name = raw.get("name")
    if not name:
        raise ConfigError(f"{where}.name is required")

    inline, file = raw.get("examples"), raw.get("file")
    if (inline is None) == (file is None):
        raise ConfigError(f"{where} must have exactly one of 'examples' or 'file'")
    if file is not None:
        return IclSetup(name=str(name), examples=_read_examples(base_dir / str(file)))
    if not isinstance(inline, list) or not inline:
        raise ConfigError(f"{where}.examples must be a non-empty list")
    return IclSetup(
        name=str(name),
        examples=tuple(
            _build_example(example, f"{where}.examples[{index}]")
            for index, example in enumerate(inline)
        ),
    )


def _read_examples(path: Path) -> tuple[IclExample, ...]:
    """Parse a JSONL example file; every non-empty line is one demonstration."""
    try:
        text = path.read_text()
    except OSError as error:
        raise ConfigError(f"cannot read icl file {path}: {error}") from error

    examples = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"icl file {path} line {number}"
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as error:
            raise ConfigError(f"{where} is not valid JSON ({error})") from None
        examples.append(_build_example(parsed, where))
    if not examples:
        raise ConfigError(f"icl file {path} has no examples")
    return tuple(examples)


def _build_example(raw: Any, where: str) -> IclExample:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where} must be an object")
    row, output = raw.get("input"), raw.get("output")
    if not isinstance(row, Mapping) or not isinstance(output, str):
        raise ConfigError(f"{where} must have 'input' (object) and 'output' (string)")
    return IclExample(input=dict(row), output=output)


# How each strategy picks the setup for attempt number `index` (0-based).
_CHOICES = {
    "fixed": lambda setups, index: setups[0],
    "round_robin": lambda setups, index: setups[index % len(setups)],
    "random": lambda setups, index: random.choice(setups),
    DECLARED_ORDER: lambda setups, index: setups[index],
}


def select_setup(config: IclConfig | None, strategy: str | None, index: int) -> IclSetup | None:
    """The setup for attempt `index`, or `None` when the task has no ICL."""
    if config is None or strategy is None:
        return None
    return _CHOICES[strategy](config.setups, index)


def examples_for(config: IclConfig | None, setup: IclSetup | None) -> Sequence[IclExample]:
    """The demonstrations to send, truncated to `k` when one is configured."""
    if config is None or setup is None:
        return ()
    return setup.examples if config.k is None else setup.examples[: config.k]
