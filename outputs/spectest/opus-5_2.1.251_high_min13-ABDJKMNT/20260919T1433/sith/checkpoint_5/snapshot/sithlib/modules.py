"""Renaming the file or directory a module lives in.

A module's name is written in two places an editor has to keep in step: the
dotted path of an import statement, which no name node covers, and the local
name that import binds. This module finds the module a cursor points at inside
an import path, and rewrites every import path that reaches a renamed module.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .analysis import Analyzer, SourceModule
from .definitions import qualified
from .edits import Edit, RefactorError, rewrite
from .importing import package_above
from .project import INIT, Project
from .source import Source

FROM = "from"


@dataclass(frozen=True)
class Written:
    """A module path as an import statement spells it.

    ``leaf_only`` marks the path of a `from ... import name` alias: the name
    is a module only as a whole, since the package before it is written
    somewhere else in the same statement.
    """

    dotted: str
    line: int
    leaf_column: int
    """Column the last segment of the path starts at."""
    leaf_only: bool = False

    def segments(self) -> Iterator[Tuple[str, str, int]]:
        """Each path this one spells, with its last segment and that column."""
        parts = self.dotted.split(".")
        start = self.leaf_column - (len(self.dotted) - len(parts[-1]))
        for index in range(len(parts) - 1 if self.leaf_only else 0, len(parts)):
            dotted = ".".join(parts[:index + 1])
            yield dotted, parts[index], start + len(dotted) - len(parts[index])


def module_in_import(source: Source, project: Project, line: int, col: int) -> Optional[Analyzer]:
    """The module the cursor points at inside an import path, if any.

    A cursor inside `import pkg.inner` or `from pkg.inner import name` names
    the segment it sits on, so `pkg` and `inner` are separate answers.
    """
    analyzer = project.analyzer_for(source)
    for node in ast.walk(source.tree):
        for written in _written_paths(node, source.lines):
            dotted = _segment_at(written, line, col)
            if dotted is not None:
                return _analyzed(project, analyzer, _level(node), dotted)
    return None


def module_value(value) -> Optional[Analyzer]:
    """The analysed module a resolved value stands for, if it is one."""
    return value.analyzer if isinstance(value, SourceModule) else None


def moved_path(path: Path, new_name: str) -> Tuple[Path, Path]:
    """Where a module's file or package directory moves when it is renamed."""
    old = path.parent if path.name == INIT else path
    new = old.with_name(new_name if old.is_dir() else new_name + ".py")
    if new.exists():
        raise RefactorError(f"path already exists: {new.name}")
    return old, new


def import_edits(project: Project, target: Analyzer, new_name: str) -> Iterator[Edit]:
    """Rewrite the renamed segment of every import path reaching a module."""
    wanted = target.path.resolve()
    for path in project.files():
        analyzer = project.analyzer_at(path)
        for node in ast.walk(analyzer.tree):
            for written in _written_paths(node, analyzer.lines):
                yield from _path_edits(project, analyzer, _level(node), written, wanted, new_name)


def _path_edits(project, analyzer, level, written: Written, wanted: Path, new_name: str):
    """The edit rewriting the segment of one import path that names a module."""
    for dotted, segment, column in written.segments():
        reached = _file_of(project, analyzer, level, dotted)
        if reached is not None and reached.resolve() == wanted:
            yield rewrite(analyzer.path, written.line, column, segment, new_name)


def _written_paths(node: ast.AST, lines: List[str]) -> Iterator[Written]:
    """The module paths an import statement writes.

    `import a.b` writes one path per alias; `from a.b import c` writes the
    path after `from` and, since `c` may itself be a module, `a.b.c` too.
    """
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield Written(alias.name, alias.lineno, _leaf_column(alias))
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            line, column = _module_position(node, lines)
            yield Written(node.module, line, column + len(node.module) - len(node.module.split(".")[-1]))
        for alias in node.names:
            yield Written(qualified(node.module or "", alias.name), alias.lineno, alias.col_offset, True)


def _leaf_column(alias: ast.alias) -> int:
    """Column the last segment of a plain import's dotted path starts at."""
    return alias.col_offset + len(alias.name) - len(alias.name.split(".")[-1])


def _module_position(node: ast.ImportFrom, lines: List[str]) -> Tuple[int, int]:
    """Where the dotted path of a `from` import starts on its line."""
    text = lines[node.lineno - 1]
    column = text.index(FROM, node.col_offset) + len(FROM)
    while column < len(text) and text[column] in " \t.":
        column += 1
    return node.lineno, column


def _segment_at(written: Written, line: int, col: int) -> Optional[str]:
    """The path up to the segment a cursor sits on, or ``None`` if it is elsewhere."""
    for dotted, segment, column in written.segments():
        if line == written.line and column <= col <= column + len(segment):
            return dotted
    return None


def _level(node: ast.AST) -> int:
    """How many leading dots an import path was written with."""
    return node.level if isinstance(node, ast.ImportFrom) else 0


def _analyzed(project: Project, analyzer: Analyzer, level: int, dotted: str) -> Optional[Analyzer]:
    """The analysis of the module a written path names."""
    path = _file_of(project, analyzer, level, dotted)
    return project.analyzer_at(path) if path is not None else None


def _file_of(project: Project, analyzer: Analyzer, level: int, dotted: str) -> Optional[Path]:
    """The project file a written import path names, relative paths included."""
    if not level:
        return project.file_of(dotted)
    base = package_above(analyzer.package, level)
    return project.file_of(qualified(base, dotted)) if base is not None else None
