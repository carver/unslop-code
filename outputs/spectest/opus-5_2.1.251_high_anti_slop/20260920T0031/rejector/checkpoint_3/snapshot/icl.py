"""In-context learning setups: their examples, the turns they add and how one is picked.

A setup is a named list of demonstrations, given inline or in a JSONL file. Its
examples are rendered once per task with the task's own user template and then
sit between the system message and the row's user message as alternating
user/assistant turns.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from typing import Any

from errors import RejectorError
from templates import Message

FIXED = "fixed"
RANDOM = "random"
ROUND_ROBIN = "round_robin"
STRATEGIES = (FIXED, RANDOM, ROUND_ROBIN)


@dataclass(frozen=True)
class IclExample:
    """One demonstration: a row-shaped input and the assistant reply it should get."""

    input: dict[str, Any]
    output: str


@dataclass(frozen=True)
class IclSetup:
    """A named list of demonstrations."""

    name: str
    examples: tuple[IclExample, ...]


@dataclass(frozen=True)
class IclConfig:
    """The setups a task may draw on, how many examples to show and how one is chosen."""

    setups: tuple[IclSetup, ...]
    strategy: str
    #: Examples shown from the chosen setup; None shows all of them.
    k: int | None


@dataclass(frozen=True)
class RenderedSetup:
    """A setup's demonstrations already rendered into chat messages."""

    name: str
    messages: tuple[Message, ...]


def load_setups(raw: Any, config_dir: str, prefix: str) -> tuple[IclSetup, ...]:
    """Build every configured setup, reading file-backed ones so bad files fail the run early."""
    if not isinstance(raw, list) or not raw:
        raise RejectorError(f"{prefix}.setups must be a non-empty list")
    return tuple(_setup(entry, config_dir, f"{prefix}.setups[{index}]") for index, entry in enumerate(raw))


def render_setups(config: IclConfig | None, user_template: str) -> tuple[RenderedSetup, ...]:
    """Render each setup's first `k` examples; tasks without ICL render nothing."""
    if config is None:
        return ()
    return tuple(
        RenderedSetup(name=setup.name, messages=_example_messages(setup, user_template, config.k))
        for setup in config.setups
    )


def select(setups: tuple[RenderedSetup, ...], strategy: str, attempt: int) -> RenderedSetup:
    """The setup an attempt uses: the first one, a random one, or the next in the cycle."""
    if strategy == RANDOM:
        return random.choice(setups)
    if strategy == ROUND_ROBIN:
        return setups[attempt % len(setups)]
    return setups[0]


def _setup(entry: Any, config_dir: str, prefix: str) -> IclSetup:
    """One setup section; `file` paths are resolved against the config file's directory."""
    if not isinstance(entry, dict) or not entry.get("name"):
        raise RejectorError(f"{prefix}.name is required")

    inline, path = entry.get("examples"), entry.get("file")
    if (inline is None) == (path is None):
        raise RejectorError(f"{prefix} must have exactly one of 'examples' or 'file'")

    if path is None:
        examples = _inline_examples(inline, prefix)
    else:
        examples = _file_examples(os.path.join(config_dir, str(path)))
    if not examples:
        raise RejectorError(f"{prefix} has no examples")
    return IclSetup(name=str(entry["name"]), examples=examples)


def _inline_examples(raw: Any, prefix: str) -> tuple[IclExample, ...]:
    if not isinstance(raw, list):
        raise RejectorError(f"{prefix}.examples must be a list")
    return tuple(_example(entry, f"{prefix}.examples[{index}]") for index, entry in enumerate(raw))


def _file_examples(path: str) -> tuple[IclExample, ...]:
    """Read a JSONL example file, naming the offending line when one is malformed."""
    examples = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                examples.append(_example(_parse_line(line, f"{path}:{number}"), f"{path}:{number}"))
    return tuple(examples)


def _parse_line(line: str, where: str) -> Any:
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        raise RejectorError(f"{where}: invalid JSON ({exc.msg})") from None


def _example(entry: Any, where: str) -> IclExample:
    """One demonstration; `where` names it in error messages."""
    if not isinstance(entry, dict) or not isinstance(entry.get("input"), dict):
        raise RejectorError(f"{where}: 'input' must be an object")
    if not isinstance(entry.get("output"), str):
        raise RejectorError(f"{where}: 'output' must be a string")
    return IclExample(input=entry["input"], output=entry["output"])


def _example_messages(setup: IclSetup, user_template: str, k: int | None) -> tuple[Message, ...]:
    """The first `k` examples as alternating user and assistant turns."""
    messages = []
    for example in setup.examples[:k]:
        messages.append({"role": "user", "content": _render(user_template, example.input, setup.name)})
        messages.append({"role": "assistant", "content": example.output})
    return tuple(messages)


def _render(template: str, values: dict[str, Any], setup_name: str) -> str:
    try:
        return template.format_map(values)
    except KeyError as exc:
        raise RejectorError(f"icl setup '{setup_name}': example input is missing field {exc}") from None
