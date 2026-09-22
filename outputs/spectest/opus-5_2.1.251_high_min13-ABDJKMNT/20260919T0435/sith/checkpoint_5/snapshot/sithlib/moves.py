"""Renaming a module: the file it lives in, and every import that names it."""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass

from . import definitions, paths, project
from .edits import Buffer, Workspace
from .navigate import definitions_at
from .source import SithError, parse_tolerant
from .symbols import MODULE

PACKAGE_FILE = "__init__.py"

#: The module part of a `from` statement, however many dots lead it.
FROM = re.compile(r"\s*from\s+(?P<dots>\.*)(?P<module>[\w.]*)")
IMPORT = re.compile(r"\bimport\b")
#: One `a.b as c` entry of an `import` statement.
IMPORTED = re.compile(r"(?P<module>[\w.]+)(\s+as\s+\w+)?")


@dataclass(frozen=True)
class Module:
    """A project module named at the cursor, which a rename would move."""

    name: str
    #: The file, or for a package the directory, relative to the project root.
    path: str
    is_package: bool

    def moved_to(self, new_name: str) -> str:
        """Where the module lands once its last name segment is replaced."""
        leaf = new_name if self.is_package else f"{new_name}.py"
        return paths.posix(os.path.join(os.path.dirname(self.path), leaf))

    def renamed(self, new_name: str) -> str:
        """The dotted name the module answers to after the rename."""
        return ".".join(self.name.split(".")[:-1] + [new_name])


def module_at(analysis, reference, col: int, root: str) -> Module | None:
    """The project module the cursor names, or None when it names anything else."""
    dotted = _module_in_import(analysis, col) or _resolved_module(analysis, reference)
    return _locate(root, dotted) if dotted else None


def rename_module(workspace: Workspace, module: Module, new_name: str) -> None:
    """Move a module's file and rewrite every import and use of it."""
    moved = module.renamed(new_name)
    if _locate(workspace.root, moved) is not None:
        raise SithError(f"a module named {moved} already exists")
    workspace.rename_path(module.path, module.moved_to(new_name))
    for path in project.python_files(workspace.root):
        buffer = workspace.buffer(paths.relative(path, workspace.root))
        package = _package_of(paths.qualified_name(path, workspace.root),
                              os.path.basename(path) == PACKAGE_FILE)
        _rewrite_file(buffer, parse_tolerant(buffer.lines), module.name, moved, package)


def _module_in_import(analysis, col: int) -> str | None:
    """The module the cursor points at inside an import statement.

    An import statement is the one place a module is named as bare text rather
    than as an expression, so it is read here instead of being resolved.  A
    cursor part-way along a dotted name means the module that segment ends.
    """
    match = FROM.match(analysis.line_text)
    if match is None:
        return _imported_module(analysis.line_text, col)
    if not match["module"] or not match.start("module") <= col <= match.end("module"):
        return None
    module = analysis.resolver.module
    return _absolute(_up_to(match, col), len(match["dots"]),
                     _package_of(module.name, module.directory is not None))


def _imported_module(line_text: str, col: int) -> str | None:
    """The module the cursor points at in an `import a.b, c` statement."""
    keyword = re.match(r"\s*import\s+", line_text)
    if keyword is None:
        return None
    for entry in IMPORTED.finditer(line_text, keyword.end()):
        if entry.start("module") <= col <= entry.end("module"):
            return _up_to(entry, col)
    return None


def _up_to(match: re.Match, col: int) -> str:
    """The dotted name the cursor sits in, cut off after the segment it is on."""
    written = match["module"]
    inside = col - match.start("module")
    return written[:inside] + written[inside:].partition(".")[0]


def _resolved_module(analysis, reference) -> str | None:
    """The dotted name of the module the cursor's name stands for, if it is one."""
    found = [
        definition
        for definition in definitions_at(analysis, reference)
        if definition.kind == MODULE and definition.module_path
    ]
    return found[0].full_name if len(found) == 1 else None


def _package_of(name: str, is_package: bool) -> str:
    """The dotted name of the package a module's relative imports count from."""
    return name if is_package else name.rpartition(".")[0]


def _absolute(dotted: str, level: int, package: str) -> str:
    """A possibly relative module name, seen from the project root."""
    if not level:
        return dotted
    parts = package.split(".") if package else []
    return ".".join([part for part in parts[: len(parts) - level + 1] + [dotted] if part])


def _locate(root: str, dotted: str) -> Module | None:
    """The file or package directory a dotted name lives in, inside the project."""
    base = os.path.join(root, *dotted.split("."))
    if os.path.isfile(f"{base}.py"):
        return Module(dotted, paths.relative(f"{base}.py", root), False)
    if os.path.isfile(os.path.join(base, PACKAGE_FILE)):
        return Module(dotted, paths.relative(base, root), True)
    return None


def _rewrite_file(buffer: Buffer, tree: ast.Module, old: str, new: str, package: str) -> None:
    """Update one file's imports of `old`, and the uses those imports let it write."""
    binds = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            binds |= _rewrite_import(buffer, node, old, new)
        elif isinstance(node, ast.ImportFrom):
            binds |= _rewrite_from(buffer, node, old, new, package)
    _rewrite_chains(buffer, tree, old, _leaf(new))
    if binds:
        _rewrite_names(buffer, tree, _leaf(old), _leaf(new))


def _rewrite_import(buffer: Buffer, node: ast.Import, old: str, new: str) -> bool:
    """Rewrite the `import a.b` statements naming the module; report a bound name."""
    binds = False
    column = _after_import(buffer, node.lineno)
    for alias in node.names:
        if _under(alias.name, old):
            column = _rewrite_dotted(buffer, node.lineno, old, new, column)
            # `import a.b` binds `a`, so only an undotted import binds the module.
            binds |= alias.asname is None and alias.name == old and "." not in old
    return binds


def _rewrite_from(buffer: Buffer, node: ast.ImportFrom, old: str, new: str,
                  package: str) -> bool:
    """Rewrite a `from ... import ...` naming the module, in either of its halves."""
    written = _absolute(node.module or "", node.level, package)
    dots = len(written) - len(node.module or "")
    if node.module and _under(written, old) and len(old) > dots:
        # The leading dots of a relative import stand for a package that the
        # rename leaves alone, so only the text after them is rewritten.
        column = _module_column(buffer, node)
        buffer.replace((node.lineno, column), (node.lineno, column + len(node.module)),
                       (new + written[len(old):])[dots:])
        return False
    binds = False
    for alias in node.names:
        if f"{written}.{alias.name}".strip(".") == old:
            binds |= _rewrite_member(buffer, node, alias, new)
    return binds


def _rewrite_member(buffer: Buffer, node: ast.ImportFrom, alias: ast.alias, new: str) -> bool:
    """Rewrite `from pkg import mod`, where the module is named as a member."""
    column = _after_import(buffer, node.lineno)
    for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
        found = re.compile(rf"\b{alias.name}\b").search(buffer.lines[line - 1], column)
        if found is not None:
            buffer.replace((line, found.start()), (line, found.end()), _leaf(new))
            return alias.asname is None
        column = 0
    return False


def _rewrite_chains(buffer: Buffer, tree: ast.Module, old: str, new: str) -> None:
    """Rewrite the module reached through its package, as in `pkg.foo.value`."""
    leaf = _leaf(old)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == leaf and _dotted(node) == old:
            line = node.value.end_lineno
            column = definitions.column_after(buffer.lines, line, node.value.end_col_offset, leaf)
            buffer.replace((line, column), (line, column + len(leaf)), new)


def _rewrite_names(buffer: Buffer, tree: ast.Module, old: str, new: str) -> None:
    """Rewrite the bare name an import of the module bound, as in `foo.value`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == old:
            buffer.replace((node.lineno, node.col_offset),
                           (node.lineno, node.col_offset + len(old)), new)


def _rewrite_dotted(buffer: Buffer, line: int, old: str, new: str, column: int) -> int:
    """Replace a dotted name written at or after a column, answering where it ended."""
    found = re.compile(rf"(?<![\w.]){re.escape(old)}(?!\w)").search(buffer.lines[line - 1], column)
    if found is None:
        return column
    buffer.replace((line, found.start()), (line, found.end()), new)
    return found.end()


def _module_column(buffer: Buffer, node: ast.ImportFrom) -> int:
    """Where the module name of a `from` statement starts."""
    return FROM.match(buffer.lines[node.lineno - 1]).start("module")


def _after_import(buffer: Buffer, line: int) -> int:
    """Where the names of an import statement start, past the keyword."""
    found = IMPORT.search(buffer.lines[line - 1])
    return found.end() if found else 0


def _leaf(dotted: str) -> str:
    """The last segment of a dotted name, which is what the module is called."""
    return dotted.rsplit(".", 1)[-1]


def _under(dotted: str, package: str) -> bool:
    """Whether a dotted name is a package itself or something inside it."""
    return dotted == package or dotted.startswith(f"{package}.")


def _dotted(node: ast.AST) -> str | None:
    """The dotted source of an attribute chain, when it is all plain names."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _dotted(node.value)
        return f"{owner}.{node.attr}" if owner else None
    return None
