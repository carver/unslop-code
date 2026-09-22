"""Renaming a module: the file or directory it lives in, and every import of it.

A module is named in two ways that a rename has to keep in step.  Import
statements spell it out as a dotted path, which is text rather than a name the
scope tree knows about, so those paths are read back out of the source here.
Everything else -- the name an ``import`` binds, the attribute a package
exposes -- is an ordinary reference and is renamed the ordinary way.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .cursor import name_at
from .edits import Edit, Refactoring, collect
from .errors import SithError
from .imports import absolute, qualified
from .project import Analysis, Project
from .references import matching, resolve
from .renaming import occurrence_edits
from .trees import Span

_FROM = re.compile(r"from\s+\.*(?P<module>[\w.]*)")


@dataclass(frozen=True)
class _Path:
    """A dotted module path as an import writes it, and where it is written.

    ``certain`` is false for the names of a ``from x import y`` clause, which
    are modules only when the project turns out to hold one of that name: ``y``
    is as likely to be a function as a submodule.
    """

    written: str
    absolute: str
    line: int
    column: int
    certain: bool = True

    def covers(self, line: int, column: int) -> bool:
        return self.line == line and self.column <= column <= self.column + len(self.written)


def module_at(project: Project, analysis: Analysis, line: int, column: int) -> str | None:
    """The module the cursor names, whether by importing it or by using it.

    An import writes the module as a dotted path, and the cursor picks out one
    component of it: in ``from pkg.core import x`` the cursor on ``core`` names
    ``pkg.core`` and on ``pkg`` names ``pkg``.  Anywhere else the cursor is on
    an ordinary name, which counts when what it refers to is a module.
    """
    for written in _written_paths(analysis):
        if written.covers(line, column):
            dotted = _component(written, column)
            if written.certain or locate(project, dotted) is not None:
                return dotted
    reference = name_at(analysis.tree, line, column)
    if reference is None:
        return None
    scope = analysis.module.scope.innermost(line)
    found = [definition for definition in resolve(reference, scope, line, follow=True)
             if definition.type == "module"]
    return found[0].full_name if found else None


def rename_module(project: Project, dotted: str, new_name: str) -> Refactoring:
    """Move the file or directory of module ``dotted`` and restate every import."""
    location = locate(project, dotted)
    if location is None:
        raise SithError(f"cannot rename '{dotted}': it is not a module of the project")
    moved = location.with_name(new_name + location.suffix)
    if locate(project, qualified(dotted.rpartition(".")[0], new_name)) is not None:
        raise SithError(f"cannot rename to '{new_name}': a module of that name already exists")
    analyses = project.analyses()
    edits = [edit for analysis in analyses.values()
             for edit in _restated(analysis, project, dotted, new_name)]
    renames = {location.relative_to(project.root).as_posix():
               moved.relative_to(project.root).as_posix()}
    return collect(edits, {path: analysis.info.text for path, analysis in analyses.items()},
                   renames)


def locate(project: Project, dotted: str) -> Path | None:
    """The file or the package directory module ``dotted`` lives in."""
    package = project.root.joinpath(*dotted.split("."))
    module = package.with_suffix(".py")
    if module.is_file():
        return module
    return package if package.is_dir() else None


def _restated(analysis: Analysis, project: Project, dotted: str, new_name: str) -> list[Edit]:
    """The edits one file needs: its import paths, then its uses of the name."""
    base = dotted.rpartition(".")[2]
    module = project.module(dotted)
    target = frozenset(module.definitions() if module is not None else [])
    found = [occurrence for occurrence, _ in matching(analysis, base, target)]
    paths = (_path_edit(analysis.info.path, written, dotted, new_name)
             for written in _written_paths(analysis))
    return [edit for edit in paths if edit is not None] + occurrence_edits(found, len(base),
                                                                          new_name)


def _path_edit(path: str, written: _Path, dotted: str, new_name: str) -> Edit | None:
    """The edit restating ``written`` when it names the module being renamed.

    Only the last component of the old name changes, and only when the import
    spells that component out: a relative import inside the package being
    renamed writes none of it, and is left alone for the directory move.
    """
    if written.absolute != dotted and not written.absolute.startswith(f"{dotted}."):
        return None
    parts = written.written.split(".")
    index = len(dotted.split(".")) - 1 - (len(written.absolute.split(".")) - len(parts))
    if index < 0:
        return None
    start = written.column + sum(len(part) + 1 for part in parts[:index])
    return Edit(path, Span(written.line, start, written.line, start + len(parts[index])),
                new_name)


def _written_paths(analysis: Analysis) -> Iterator[_Path]:
    """Every dotted module path the file writes in an import statement."""
    lines = analysis.info.text.split("\n")
    package = analysis.info.package
    for node in ast.walk(analysis.tree):
        match node:
            case ast.Import(names=aliases):
                for alias in aliases:
                    yield _Path(alias.name, alias.name, alias.lineno, alias.col_offset)
            case ast.ImportFrom(module=module, level=level, names=aliases):
                container = absolute(module or "", level, package)
                if container is None:
                    continue  # the import reaches above the project root
                if module:
                    yield _Path(module, container, node.lineno, _from_column(lines, node))
                for alias in aliases:
                    if alias.name != "*":
                        yield _Path(alias.name, qualified(container, alias.name),
                                    alias.lineno, alias.col_offset, certain=False)


def _from_column(lines: list[str], node: ast.ImportFrom) -> int:
    """The column the module path of a ``from`` import starts at."""
    written = _FROM.match(lines[node.lineno - 1], node.col_offset)
    return written.start("module") if written else node.col_offset


def _component(written: _Path, column: int) -> str:
    """The module ``written`` names up to and including the component at ``column``."""
    index = written.written.count(".", 0, column - written.column)
    parts = written.absolute.split(".")
    depth = len(parts) - len(written.written.split(".")) + index + 1
    return ".".join(parts[:depth])
