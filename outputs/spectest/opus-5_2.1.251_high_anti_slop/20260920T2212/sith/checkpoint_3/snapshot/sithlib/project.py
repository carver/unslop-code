"""Module resolution for the directory a project is rooted at.

A module name is looked for in the project root first, where it is parsed
rather than imported so that project code is never executed, and then in the
standard library, which is imported for real.  Anything else -- a third party
package, a name that does not exist -- is unresolvable and simply offers
nothing.
"""

from __future__ import annotations

import ast
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

from .builder import ScopeBuilder
from .definitions import Definition
from .errors import SithError
from .imports import exported_names, qualified
from .parsing import tolerant_parse
from .scopes import Scope
from .values import ModuleRef, RuntimeObject, SourceModule, Symbol, Value


@dataclass(frozen=True)
class ModuleInfo:
    """Which file is being analysed, under which name, with which text."""

    name: str
    path: str
    text: str

    @property
    def package(self) -> str:
        """The package a relative import written in this module starts from."""
        return self.name if self.path.endswith("__init__.py") else self.name.rpartition(".")[0]


@dataclass(frozen=True)
class Analysis:
    """A parsed file: the tree a cursor is located in and the module it binds."""

    tree: ast.Module
    module: SourceModule
    info: ModuleInfo


class Project:
    """Maps a dotted module name onto a value, relative to ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._resolved: dict[str, Value | None] = {}

    def analyse(self, path: Path, text: str) -> Analysis:
        """Parse ``path`` and record every name its module body binds."""
        info = self.info(path, text)
        # A module that imports its way back round to this one, while this one
        # is still being built, sees nothing rather than starting again.
        self._resolved.setdefault(info.name, None)
        tree = tolerant_parse(text)
        scope = ScopeBuilder(self, info).build(tree, text.count("\n") + 1)
        site = self._site(info.name, info.path, ast.get_docstring(tree) or "")
        module = SourceModule(scope, site, exported_names(tree),
                              lambda: self.modules(info.name))
        self._resolved[info.name] = module
        return Analysis(tree, module, info)

    def info(self, path: Path, text: str) -> ModuleInfo:
        """Name and locate ``path`` within the project."""
        resolved = path.resolve()
        if self.root not in resolved.parents:
            raise SithError(f"{path} is not inside the project root {self.root}")
        relative = resolved.relative_to(self.root)
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ModuleInfo(".".join(parts), relative.as_posix(), text)

    def module(self, dotted: str) -> Value | None:
        """The value of module ``dotted``, or ``None`` if it cannot be found."""
        if not dotted:
            return None
        if dotted not in self._resolved:
            self._resolved[dotted] = None  # what a circular import sees
            self._resolved[dotted] = self._resolve(dotted)
        return self._resolved[dotted]

    def modules(self, dotted: str) -> list[Symbol]:
        """The modules and packages the project holds inside ``dotted``."""
        directory = self.root.joinpath(*dotted.split(".")) if dotted else self.root
        return [self._reference(qualified(dotted, name)) for name in _contents(directory)]

    def top_level(self) -> list[Symbol]:
        """Everything a bare ``import`` can name: the project, then the stdlib."""
        found = self.modules("")
        named = {symbol.name for symbol in found}
        return found + [self._reference(name) for name in sorted(sys.stdlib_module_names)
                        if name not in named]

    def importable(self, dotted: str) -> list[Symbol]:
        """The names a ``from <dotted> import`` clause can offer.

        An empty name is the project root, which is a package holding the
        top-level modules but binding no names of its own.
        """
        module = self.module(dotted)
        return module.attributes() if module is not None else self.modules(dotted)

    # -- resolution --------------------------------------------------------

    def _resolve(self, dotted: str) -> Value | None:
        path = self._source_path(dotted)
        if path is not None:
            return self.analyse(path, path.read_text(encoding="utf-8", errors="replace")).module
        directory = self.root.joinpath(*dotted.split("."))
        if directory.is_dir():
            return self._namespace(dotted, directory)
        return self._stdlib(dotted)

    def _source_path(self, dotted: str) -> Path | None:
        parts = dotted.split(".")
        candidates = (self.root.joinpath(*parts).with_suffix(".py"),
                      self.root.joinpath(*parts, "__init__.py"))
        return next((path for path in candidates if path.is_file()), None)

    def _namespace(self, dotted: str, directory: Path) -> Value:
        """A package directory with no ``__init__.py``: only its modules exist."""
        site = self._site(dotted, directory.relative_to(self.root).as_posix(), "")
        return SourceModule(Scope("module", dotted, 1, 1), site, None,
                            lambda: self.modules(dotted))

    def _stdlib(self, dotted: str) -> Value | None:
        """A standard library module, imported for real; anything else is unknown."""
        if dotted.split(".")[0] not in sys.stdlib_module_names:
            return None
        try:
            module = importlib.import_module(dotted)
        except Exception:
            # Importing runs module level code, which may fail in any way; an
            # unresolvable module simply offers no completions.
            return None
        return RuntimeObject(module, dotted.rpartition(".")[2], "module",
                             f"module {dotted}", public_only=True)

    def _reference(self, dotted: str) -> Symbol:
        return Symbol(dotted.rpartition(".")[2], ModuleRef(dotted, lambda: self.module(dotted)))

    def _site(self, dotted: str, path: str, docstring: str) -> Definition:
        return Definition(dotted.rpartition(".")[2], "module", dotted, path, 1, 0,
                          f"module {dotted}", docstring)


def _contents(directory: Path) -> list[str]:
    """The names ``directory`` offers as modules: ``.py`` files and packages.

    A directory counts whether or not it holds an ``__init__.py``, since a
    namespace package is imported the same way a regular one is.
    """
    if not directory.is_dir():
        return []
    names = {entry.stem if entry.suffix == ".py" else entry.name
             for entry in directory.iterdir()
             if (entry.suffix == ".py" and entry.is_file()) or entry.is_dir()}
    return sorted(name for name in names - {"__init__", "__pycache__"} if name.isidentifier())
