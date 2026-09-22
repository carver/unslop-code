"""Assembling everything one request needs to know about one file."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import scopes
from .modules import LocalModule, ModuleIndex
from .resolve import Resolver
from .source import SourceFile, parse_tolerant


@dataclass(frozen=True)
class Analysis:
    """The file under the cursor, its scope tree, and a resolver placed on it."""

    source: SourceFile
    tree: scopes.ScopeTree
    resolver: Resolver
    line: int
    col: int

    @classmethod
    def at(cls, path: str, line: int, col: int) -> "Analysis":
        """Load and parse `path`, with the project root taken to be its directory."""
        source = SourceFile.load(path)
        source.validate(line, col)
        absolute = os.path.abspath(path)
        root = os.path.dirname(absolute)
        tree = scopes.build(parse_tolerant(source.lines, line))
        module = LocalModule(
            name=os.path.basename(absolute).removesuffix(".py"),
            tree=tree.root.node,
            path=os.path.relpath(absolute, root),
            lines=source.lines,
        )
        resolver = Resolver(tree, ModuleIndex(root), module, position=line)
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
