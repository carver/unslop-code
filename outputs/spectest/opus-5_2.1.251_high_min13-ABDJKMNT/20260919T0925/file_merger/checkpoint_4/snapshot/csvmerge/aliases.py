"""Type-name aliases: the built-in table, an optional alias file, and resolution.

A declaration is resolved by following its *head* name through the table until it
names something the type parser understands, so `list<int>` reaches `array<int>` and
an alias may itself expand into a generic type. Names are lowercased first, which is
what makes the whole vocabulary case-insensitive.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import AliasCycleError, SchemaError

#: Always present, regardless of `--type-alias-file`.
BUILTIN_ALIASES = {
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


class AliasTable:
    """Maps a lowercased type name onto the declaration it stands for."""

    def __init__(self, extra=None):
        lowered = {name.lower(): target.lower() for name, target in (extra or {}).items()}
        self._targets = dict(BUILTIN_ALIASES, **lowered)

    @classmethod
    def load(cls, source):
        """Build a table from an alias JSON file path, or from inline JSON."""
        if source is None:
            return cls()
        document = _read_document(source)
        aliases = document.get("aliases") if isinstance(document, dict) else None
        if not isinstance(aliases, dict):
            raise SchemaError("alias file must contain an 'aliases' object")
        if not all(isinstance(value, str) for value in aliases.values()):
            raise SchemaError("every alias must name a type")
        return cls(aliases)

    def resolve(self, declaration):
        """Return `declaration` as a `(head, arguments)` pair with aliases applied.

        `arguments` is the raw text between the angle brackets, or None for a plain
        name. A name that leads back to itself raises `AliasCycleError`.
        """
        text = declaration.strip().lower()
        seen = set()
        while True:
            head, arguments = split_generic(text)
            target = self._targets.get(head)
            if target is None:
                return head, arguments
            if head in seen:
                raise AliasCycleError(f"type alias {head!r} resolves to itself")
            seen.add(head)
            text = target if arguments is None else _reapply(target, arguments, head)


def split_generic(text):
    """Split `map<string,int>` into `("map", "string,int")`, or a name into `(name, None)`."""
    start = text.find("<")
    if start < 0:
        return text, None
    if not text.endswith(">"):
        raise SchemaError(f"unbalanced type arguments in {text!r}")
    return text[:start].strip(), text[start + 1 : -1]


def split_arguments(text):
    """Split a type argument list on its top-level commas."""
    arguments, depth, start = [], 0, 0
    for position, character in enumerate(text):
        depth += (character == "<") - (character == ">")
        if character == "," and depth == 0:
            arguments.append(text[start:position])
            start = position + 1
    arguments.append(text[start:])
    return [argument.strip() for argument in arguments]


def _reapply(target, arguments, head):
    """Re-attach the arguments of `head<...>` to the name its alias expands to."""
    if "<" in target:
        raise SchemaError(f"alias {head!r} already carries type arguments")
    return f"{target}<{arguments}>"


def _read_document(source):
    text = source if source.lstrip().startswith("{") else _read_file(source)
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise SchemaError(f"alias file is not valid JSON: {error}") from error


def _read_file(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise SchemaError(f"cannot read alias file {path}: {error}") from error
