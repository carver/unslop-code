"""Assembling everything one request needs to know about one file."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import paths, scopes
from .modules import LocalModule, ModuleIndex
from .resolve import Resolver
from .source import SourceFile, parse_tolerant

PACKAGE_FILE = "__init__.py"


@dataclass(frozen=True)
class Analysis:
    """The file under the cursor, its scope tree, and a resolver placed on it."""

    source: SourceFile
    tree: scopes.ScopeTree
    resolver: Resolver
    line: int
    col: int

    @classmethod
    def at(cls, path: str, line: int, col: int, project: str | None = None,
           follow: bool = False) -> "Analysis":
        """Load and parse `path` as a module of the project rooted at `project`.

        Without an explicit project, the root is the directory holding the file.
        The file is registered among the project's modules under its own name,
        so that a module importing it back reads the buffer being analysed.
        """
        source = SourceFile.load(path)
        source.validate(line, col)
        absolute = os.path.abspath(path)
        root = os.path.abspath(project) if project else os.path.dirname(absolute)
        tree = scopes.build(parse_tolerant(source.lines, line))
        module = LocalModule(
            name=paths.qualified_name(absolute, root),
            tree=tree.root.node,
            path=paths.relative(absolute, root),
            lines=source.lines,
            directory=_package_directory(absolute),
        )
        siblings = {}
        resolver = Resolver(tree, ModuleIndex(root), module, siblings, line, follow)
        siblings[module.name] = (resolver, tree)
        return cls(source, tree, resolver, line, col)

    @property
    def line_text(self) -> str:
        return self.source.lines[self.line - 1]

    @property
    def scope(self) -> scopes.Scope:
        """The innermost scope holding the cursor."""
        return scopes.scope_at(self.tree, self.line, self._indent)

    @property
    def _indent(self) -> int:
        """How far the cursor is indented, used to place it on a blank line."""
        before = self.line_text[: self.col]
        if not before.strip():
            return self.col
        return len(self.line_text) - len(self.line_text.lstrip())


def _package_directory(path: str) -> str | None:
    """The directory a file is the package of, when the file is an `__init__.py`."""
    return os.path.dirname(path) if os.path.basename(path) == PACKAGE_FILE else None
