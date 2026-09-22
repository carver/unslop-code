"""Finding the module behind an import statement.

Project modules sitting next to the analysed file are read statically, so that
completing against a half-written project never executes it.  Anything else is
imported, which is the only way to enumerate an installed package's names.
"""

from __future__ import annotations

import ast
import importlib
import os
from dataclasses import dataclass

from .source import parse_tolerant


@dataclass(frozen=True)
class LocalModule:
    """A project `.py` file, resolved by parsing rather than importing.

    `path` is relative to the project root and `lines` is the file's text, both
    of which the definition records of `infer` and `goto` are built from.
    """

    name: str
    tree: ast.Module
    path: str
    lines: list[str]

    @classmethod
    def read(cls, name: str, path: str, root: str) -> "LocalModule | None":
        try:
            text = open(path, "rb").read().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        lines = text.splitlines() or [""]
        return cls(name, parse_tolerant(lines), os.path.relpath(path, root), lines)


@dataclass(frozen=True)
class RuntimeModule:
    """An installed module, resolved by importing it."""

    name: str
    module: object


class ModuleIndex:
    """Caches module lookups made while analysing one file."""

    def __init__(self, directory: str) -> None:
        self.directory = directory
        self._cache: dict[str, LocalModule | RuntimeModule | None] = {}

    def resolve(self, dotted: str) -> LocalModule | RuntimeModule | None:
        if dotted not in self._cache:
            self._cache[dotted] = self._lookup(dotted)
        return self._cache[dotted]

    def _lookup(self, dotted: str) -> LocalModule | RuntimeModule | None:
        return self._local(dotted) or self._installed(dotted)

    def _local(self, dotted: str) -> LocalModule | None:
        path = os.path.join(self.directory, *dotted.split(".")) + ".py"
        if not os.path.isfile(path):
            return None
        return LocalModule.read(dotted, path, self.directory)

    def _installed(self, dotted: str) -> RuntimeModule | None:
        try:
            return RuntimeModule(dotted, importlib.import_module(dotted))
        except Exception:
            # Importing third-party code can fail in arbitrary ways; an import
            # that does not load simply yields no completions.
            return None
