"""Finding the module behind an import statement.

Modules are searched for along the project's own import path first, by parsing
rather than importing, so that analysing a half-written project never executes
it.  What that path does not hold is looked for in the standard library, which
has to be imported: that is the only way to enumerate a compiled module's
names.  A module found in neither place is unresolvable, and answers nothing.
"""

from __future__ import annotations

import ast
import importlib
import os
import pkgutil
import sys
from dataclasses import dataclass, field

from . import paths, stubs
from .source import parse_tolerant

EMPTY_TREE = ast.Module(body=[], type_ignores=[])
NOT_IMPORTABLE = {"__pycache__", "__init__"}


@dataclass(frozen=True)
class LocalModule:
    """A project module, resolved by parsing rather than importing.

    `name` is its dotted name under the project root and `path` is its file
    seen from that root; both feed the records `infer` and `goto` answer with.
    `directory` is set for a package, whose submodules are files beside it.
    """

    name: str
    tree: ast.Module
    path: str
    lines: list[str] = field(default_factory=list)
    directory: str | None = None

    @classmethod
    def read(cls, name: str, path: str, root: str, directory: str | None = None):
        try:
            text = open(path, "rb").read().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        lines = text.splitlines() or [""]
        return cls(name, parse_tolerant(lines), paths.relative(path, root), lines, directory)

    @classmethod
    def namespace(cls, name: str, directory: str, root: str) -> "LocalModule":
        """A package directory with no `__init__.py`, which binds no names of its own."""
        return cls(name, EMPTY_TREE, paths.relative(directory, root), directory=directory)

    @property
    def exports(self) -> list[str] | None:
        """The names listed in `__all__`, or None when the module defines none."""
        for statement in self.tree.body:
            names = _assigned_all(statement)
            if names is not None:
                return names
        return None

    def submodules(self) -> list[str]:
        return _directory_modules(self.directory) if self.directory else []


@dataclass(frozen=True)
class RuntimeModule:
    """A standard-library module, resolved by importing it."""

    name: str
    module: object

    @property
    def exports(self) -> list[str] | None:
        listed = getattr(self.module, "__all__", None)
        return list(listed) if listed is not None else None

    def submodules(self) -> list[str]:
        search_path = getattr(self.module, "__path__", None)
        return [found.name for found in pkgutil.iter_modules(search_path)] if search_path else []


class ModuleIndex:
    """The directories an import is searched in, with lookups cached.

    `root` is the project root, which names the modules found and locates them
    in the output; `search_paths` is where they are looked for, which the
    project configuration may extend or replace.
    """

    def __init__(self, root: str, search_paths: list[str] | None = None) -> None:
        self.root = root
        self.search_paths = [root] if search_paths is None else list(search_paths)
        self._cache: dict[str, LocalModule | RuntimeModule | None] = {}
        self._stubs: dict[str, LocalModule | None] = {}

    def resolve(self, dotted: str) -> LocalModule | RuntimeModule | None:
        """The module a dotted name refers to, or None when it is unresolvable."""
        if not dotted:
            return None
        if dotted not in self._cache:
            self._cache[dotted] = self._project(dotted) or _stdlib(dotted)
        return self._cache[dotted]

    def stub_for(self, dotted: str) -> LocalModule | None:
        """The `.pyi` describing a module, or None when it has no stub."""
        if dotted not in self._stubs:
            self._stubs[dotted] = self._read_stub(dotted)
        return self._stubs[dotted]

    def _read_stub(self, dotted: str) -> LocalModule | None:
        found = (p for p in stubs.search_paths(self.root, dotted) if os.path.isfile(p))
        path = next(found, None)
        return LocalModule.read(dotted, path, self.root) if path else None

    def top_level(self) -> list[str]:
        """Every name that can follow `import`: project modules, then the stdlib."""
        return self.project_modules() + sorted(sys.stdlib_module_names)

    def project_modules(self) -> list[str]:
        """The modules and packages an `import` offers: those of the project root.

        The search path may reach further -- into the packages of the project,
        or wherever the configuration points it -- but what `import` completes
        to is what the project is written to import.
        """
        return _directory_modules(self.root)

    def submodules(self, dotted: str) -> list[str]:
        handle = self.resolve(dotted)
        return handle.submodules() if handle else []

    def _project(self, dotted: str) -> LocalModule | None:
        """A module on the search path, the earliest directory holding it winning."""
        found = (self._under(path, dotted) for path in self.search_paths)
        return next((module for module in found if module is not None), None)

    def _under(self, search_path: str, dotted: str) -> LocalModule | None:
        """A module inside one search directory; a package wins over a same-named file."""
        directory = os.path.join(search_path, *dotted.split("."))
        initializer = os.path.join(directory, "__init__.py")
        if os.path.isfile(initializer):
            return LocalModule.read(dotted, initializer, self.root, directory)
        if os.path.isfile(f"{directory}.py"):
            return LocalModule.read(dotted, f"{directory}.py", self.root)
        if os.path.isdir(directory):
            return LocalModule.namespace(dotted, directory, self.root)
        return None


def _stdlib(dotted: str) -> RuntimeModule | None:
    if dotted.split(".")[0] not in sys.stdlib_module_names:
        return None
    try:
        return RuntimeModule(dotted, importlib.import_module(dotted))
    except Exception:
        # A stdlib module can fail to import when its extension was not built;
        # an import that does not load simply yields no completions.
        return None


def _directory_modules(directory: str) -> list[str]:
    """The importable names a directory offers: `.py` files and subdirectories."""
    try:
        entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
    except OSError:
        return []
    found = []
    for entry in entries:
        name = entry.name.removesuffix(".py") if entry.is_file() else entry.name
        offered = entry.name.endswith(".py") if entry.is_file() else entry.is_dir()
        if offered and name.isidentifier() and name not in NOT_IMPORTABLE:
            found.append(name)
    # A package and a same-named module may both be present; name them once.
    return list(dict.fromkeys(found))


def _assigned_all(statement: ast.stmt) -> list[str] | None:
    """The string elements of an `__all__ = [...]` statement, if that is what it is."""
    if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
        return None
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    named = any(isinstance(node, ast.Name) and node.id == "__all__" for node in targets)
    if not named or not isinstance(statement.value, (ast.List, ast.Tuple)):
        return None
    return [node.value for node in statement.value.elts if _is_string(node)]


def _is_string(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)
