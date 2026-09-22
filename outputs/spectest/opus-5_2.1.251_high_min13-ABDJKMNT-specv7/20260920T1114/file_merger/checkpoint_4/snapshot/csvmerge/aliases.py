"""Type-name aliases: the built-in set and the optional `--type-alias-file`.

A type name is lowercased, then its head — the part before any `<...>` — is
followed through the alias table until it names a kind `csvmerge.typespec`
knows. Cycles are detected when the table is built, so following a head always
terminates (ambiguity T48).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from csvmerge.errors import EXIT_USAGE, MergeError

BUILT_IN = {
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
class TypeName:
    """A type name split into its head and, when parameterised, its arguments."""

    head: str
    args: tuple[str, ...] | None


def split_name(text: str) -> TypeName:
    """Split `map<string,array<int>>` into its head and top-level arguments."""
    name = text.strip().lower()
    if not name.endswith(">"):
        return TypeName(name, None)
    head, _, arguments = name.partition("<")
    return TypeName(head.strip(), _arguments(arguments[:-1]))


class AliasTable:
    """The names that stand for other types, built-ins plus the alias file."""

    def __init__(self, extra: dict[str, str] | None = None):
        self._aliases = {**BUILT_IN, **(extra or {})}
        self._reject_cycles()

    def resolve(self, text: str) -> TypeName:
        """Follow the head of `text` through the table, keeping its arguments."""
        name = split_name(text)
        while name.head in self._aliases:
            target = split_name(self._aliases[name.head])
            arguments = name.args if name.args is not None else target.args
            name = TypeName(target.head, arguments)
        return name

    def _reject_cycles(self) -> None:
        """Refuse a table in which following some head would loop for ever."""
        for start, target in self._aliases.items():
            seen = {start}
            head = split_name(target).head
            while head in self._aliases:
                if head in seen:
                    raise MergeError(f"type alias cycle at {head!r}", EXIT_USAGE)
                seen.add(head)
                head = split_name(self._aliases[head]).head


def load_aliases(path: str | None) -> AliasTable:
    """Read `--type-alias-file`, or build the table from the built-ins alone."""
    if path is None:
        return AliasTable()
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MergeError(
            f"cannot read type aliases {path}: {error}", EXIT_USAGE
        ) from error
    aliases = document.get("aliases") if isinstance(document, dict) else None
    if not isinstance(aliases, dict):
        raise MergeError(
            f"type alias file {path} must be an object with an 'aliases' object",
            EXIT_USAGE,
        )
    return AliasTable({str(k).lower(): str(v).lower() for k, v in aliases.items()})


def _arguments(text: str) -> tuple[str, ...]:
    """The comma-separated arguments of a generic name, nesting respected."""
    arguments, depth, start = [], 0, 0
    for index, character in enumerate(text):
        if character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
        elif character == "," and depth == 0:
            arguments.append(text[start:index])
            start = index + 1
    arguments.append(text[start:])
    return tuple(argument.strip() for argument in arguments)
