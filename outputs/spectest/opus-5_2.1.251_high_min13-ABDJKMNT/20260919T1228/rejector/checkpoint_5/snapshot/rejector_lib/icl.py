"""In-context learning setups: their config, their turns, and their rotation.

A setup is validated and rendered into the user/assistant turns it contributes
while the config is loaded, so a broken example file stops the run before any
API request. At run time a task's `IclConfig` only has to hand out the setup
each successive attempt should use.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from itertools import cycle, repeat
from pathlib import Path
from typing import Iterator

from .errors import ConfigError

STRATEGIES = ("fixed", "random", "round_robin")
DEFAULT_STRATEGY = "fixed"


@dataclass(frozen=True)
class IclSetup:
    """One named setup, already rendered into the turns it prepends."""

    name: str
    messages: tuple[dict, ...]


@dataclass(frozen=True)
class IclConfig:
    """The setups a task may draw on, and how it picks between them."""

    setups: tuple[IclSetup, ...]
    strategy: str


def build_icl(raw, user_template: str, config_dir: Path) -> IclConfig | None:
    """Validate a task's `icl` block, rendering every setup it declares."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("task.icl must be a mapping")

    setups = raw.get("setups")
    if not isinstance(setups, list) or not setups:
        raise ConfigError("icl.setups must be a non-empty list of setups")

    strategy = raw.get("strategy", DEFAULT_STRATEGY)
    if strategy not in STRATEGIES:
        raise ConfigError(
            f"icl.strategy must be one of {', '.join(STRATEGIES)}, got {strategy!r}"
        )
    return IclConfig(
        setups=tuple(
            _build_setup(setup, user_template, config_dir, _example_count(raw.get("k")))
            for setup in setups
        ),
        strategy=strategy,
    )


def setup_sequence(icl: IclConfig | None, ordered: bool) -> Iterator[IclSetup | None]:
    """The setup each successive attempt of one row uses.

    `ordered` is the greedy walk, which visits each setup at most once; every
    other sequence is endless and the caller's attempt budget bounds it.
    """
    if icl is None:
        return repeat(None)
    if ordered:
        return iter(icl.setups)
    if icl.strategy == "round_robin":
        return cycle(icl.setups)
    if icl.strategy == "random":
        return _random_setups(icl.setups)
    return repeat(icl.setups[0])


def _random_setups(setups: tuple[IclSetup, ...]) -> Iterator[IclSetup]:
    """Pick a setup independently for each attempt."""
    while True:
        yield random.choice(setups)


def _example_count(k) -> int | None:
    """The `k` examples to keep from each setup; None keeps all of them."""
    if k is None:
        return None
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ConfigError(f"icl.k must be a positive integer, got {k!r}")
    return k


def _build_setup(raw, user_template: str, config_dir: Path, k: int | None) -> IclSetup:
    """Validate one setup and render its first `k` examples into turns."""
    if not isinstance(raw, dict):
        raise ConfigError("each icl setup must be a mapping")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError("each icl setup requires a non-empty 'name'")
    if ("examples" in raw) == ("file" in raw):
        raise ConfigError(
            f"icl setup {name!r} needs exactly one of 'examples' or 'file'"
        )

    listed = _read_file(raw["file"], config_dir, name) if "file" in raw else raw["examples"]
    if not isinstance(listed, list):
        raise ConfigError(f"icl setup {name!r}: 'examples' must be a list")

    examples = [
        _checked_example(example, f"icl setup {name!r} example {index}")
        for index, example in enumerate(listed)
    ]
    chosen = examples if k is None else examples[:k]
    return IclSetup(
        name=name,
        messages=tuple(
            turn for example in chosen for turn in _turns(example, user_template, name)
        ),
    )


def _read_file(value, config_dir: Path, name: str) -> list:
    """Read a setup's JSONL example file, resolved against the config file."""
    if not isinstance(value, str) or not value:
        raise ConfigError(f"icl setup {name!r}: 'file' must be a path")
    path = config_dir / value
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError as exc:
        raise ConfigError(f"icl setup {name!r}: example file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"icl setup {name!r}: cannot read {path}: {exc}") from exc

    examples = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            examples.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"icl setup {name!r}: {path} line {number}: invalid JSON ({exc.msg})"
            ) from exc
    return examples


def _checked_example(example, label: str) -> dict:
    """Require the documented `{"input": object, "output": string}` shape."""
    if (
        not isinstance(example, dict)
        or not isinstance(example.get("input"), dict)
        or not isinstance(example.get("output"), str)
    ):
        raise ConfigError(
            f"{label} must be an object with an 'input' object and an 'output' string"
        )
    return example


def _turns(example: dict, user_template: str, name: str) -> list[dict]:
    """The user/assistant pair one example contributes to every request."""
    try:
        rendered = user_template.format(**example["input"])
    except KeyError as exc:
        raise ConfigError(
            f"icl setup {name!r}: example input is missing field {exc}"
        ) from exc
    return [
        {"role": "user", "content": rendered},
        {"role": "assistant", "content": example["output"]},
    ]
