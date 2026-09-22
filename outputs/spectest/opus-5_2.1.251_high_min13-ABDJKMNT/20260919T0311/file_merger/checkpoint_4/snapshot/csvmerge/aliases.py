"""Type aliases: the built-in table, an optional alias file, and their resolution."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .errors import EXIT_USAGE, MergeError

#: Always available, whether or not `--type-alias-file` is given. `list` is a
#: head rewrite, so `list<T>` becomes `array<T>`; `json` names the type that
#: accepts any JSON value.
BUILT_IN_ALIASES = {
    "integer": "int",
    "long": "int",
    "double": "float",
    "number": "float",
    "boolean": "bool",
    "datetime": "timestamp",
    "timestamptz": "timestamp",
    "text": "string",
    "varchar": "string",
    "list": "array",
    "json": "struct",
}


@dataclass(frozen=True)
class Aliases:
    """A lowercased name-to-name table, resolved transitively."""

    table: dict[str, str]

    def resolve(self, text: str) -> str:
        """Follow aliases from `text` until the name is not one of them.

        A generic name is followed by its head, so `list<int>` resolves through
        the `list` entry and keeps its argument.
        """
        name, seen = text.strip().lower(), set()
        while True:
            if name in seen:
                raise MergeError(f"type alias cycle at {name!r}", EXIT_USAGE)
            seen.add(name)
            head, angle, arguments = name.partition("<")
            target = self.table.get(head.strip())
            if target is None:
                return name
            name = target + angle + arguments


def load_aliases(source: str | None) -> Aliases:
    """The built-in aliases, extended by `--type-alias-file` when one is given."""
    if source is None:
        return Aliases(dict(BUILT_IN_ALIASES))
    document = _read_document(source)
    entries = document.get("aliases") if isinstance(document, dict) else None
    if not isinstance(entries, dict):
        raise MergeError("alias document must contain an 'aliases' object", EXIT_USAGE)
    declared = {name.strip().lower(): _target(name, value) for name, value in entries.items()}
    return Aliases({**BUILT_IN_ALIASES, **declared})


def _read_document(source: str):
    text = source if source.lstrip().startswith("{") else Path(source).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise MergeError(f"invalid alias JSON: {exc}", EXIT_USAGE) from None


def _target(name: str, value) -> str:
    if not isinstance(value, str):
        raise MergeError(f"alias {name!r} must name a type", EXIT_USAGE)
    return value.strip().lower()
