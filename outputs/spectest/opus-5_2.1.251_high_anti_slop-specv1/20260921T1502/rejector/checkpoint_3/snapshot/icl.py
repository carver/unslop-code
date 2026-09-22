"""In-context learning setups: their examples, their files and how one is picked.

A setup is a named list of demonstrations that are replayed as chat turns ahead
of the real question. Parsing of the `icl` config section lives in `config.py`;
this module owns the shapes it produces and the per attempt selection.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from errors import UsageError

STRATEGIES = ("fixed", "random", "round_robin")
DEFAULT_STRATEGY = "fixed"


@dataclass(frozen=True)
class Example:
    """One demonstration: a row like input and the assistant reply it should draw."""

    input: dict
    output: str


@dataclass(frozen=True)
class Setup:
    """A named list of demonstrations, already narrowed to `icl.k` examples."""

    name: str
    examples: list[Example]


@dataclass(frozen=True)
class Icl:
    """The setups a task may draw on and the strategy that picks between them."""

    setups: list[Setup]
    strategy: str


def read_examples(path: Path, where: str) -> list[Example]:
    """Parse a file backed setup: one `{"input": {...}, "output": "..."}` per line."""
    try:
        text = path.read_text()
    except OSError as error:
        raise UsageError(f"{where}: cannot read {path}: {error.strerror}") from None

    examples = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        examples.append(build_example(_decode(line, f"{path} line {number}"), f"{path} line {number}"))
    return examples


def build_example(entry: Any, where: str) -> Example:
    """Validate one example mapping, whether it came from YAML or from a JSONL line."""
    if not isinstance(entry, dict) or not isinstance(entry.get("input"), dict):
        raise UsageError(f"{where}: 'input' must be a mapping")
    if not isinstance(entry.get("output"), str):
        raise UsageError(f"{where}: 'output' must be a string")
    return Example(entry["input"], entry["output"])


def _decode(line: str, where: str) -> Any:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        raise UsageError(f"{where} is not valid JSON") from None


_STRATEGIES = {
    "fixed": lambda setups, attempt: setups[0],
    "random": lambda setups, attempt: random.choice(setups),
    "round_robin": lambda setups, attempt: setups[attempt % len(setups)],
}


def choose_setup(icl: Icl | None, attempt: int) -> Setup | None:
    """The setup for a zero based attempt index, or None when the task has no ICL."""
    if icl is None:
        return None
    return _STRATEGIES[icl.strategy](icl.setups, attempt)


def greedy_setups(icl: Icl | None, num_solutions: int) -> list[Setup | None]:
    """The setups a greedy row walks.

    Greedy decoding repeats itself, so a setup is worth at most one attempt and
    the declared order is walked instead of the configured strategy. A single
    solution run has nothing to walk and follows the strategy as usual.
    """
    if icl is None or num_solutions == 1:
        return [choose_setup(icl, 0)]
    return list(icl.setups[:num_solutions])
