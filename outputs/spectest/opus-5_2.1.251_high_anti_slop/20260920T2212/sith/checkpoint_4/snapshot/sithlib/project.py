"""Module resolution for the directory a project is rooted at.

A module name is looked for in the project root first, where it is parsed
rather than imported so that project code is never executed, and then in the
standard library, which is imported for real.  Anything else -- a third party
package, a name that does not exist -- is unresolvable and simply offers
nothing.

A module the project also ships a ``.pyi`` stub for is described by that stub:
see :mod:`sithlib.stubs`.
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
from .source import read
from .stubs import Stubbed, implemented, relocate, stub_path
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
        initialiser = self.path.rpartition("/")[2].startswith("__init__.")
        return self.name if initialiser else self.name.rpartition(".")[0]


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
        self._stubs: dict[str, Value | None] = {}
        self._analyses: dict[ModuleInfo, Analysis] = {}

    def analyse(self, path: Path, text: str) -> Analysis:
        """Parse ``path`` and record every name its module body binds.

        The analysis is the implementation as written, stub or no stub, because
        that is the file a cursor sits in and the file names are reported from;
        the module the rest of the project imports is the stubbed one.
        """
        info = self.info(path, text)
        if info not in self._analyses:
            # A module that imports its way back round to this one, while this
            # one is still being built, sees nothing rather than starting again.
            self._resolved.setdefault(info.name, None)
            self._analyses[info] = self._parse(info)
            self._resolved[info.name] = self._declared(info.name,
                                                       self._analyses[info].module)
        return self._analyses[info]

    def sources(self) -> list[Path]:
        """Every ``.py`` file the project holds, in path order."""
        return sorted(path for path in self.root.rglob("*.py")
                      if _is_source(path.relative_to(self.root)))

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
            self._resolved[dotted] = self._declared(dotted, self._resolve(dotted))
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

    def _parse(self, info: ModuleInfo, written: dict[str, Definition] | None = None) -> Analysis:
        """Turn one file's text into the module its body describes.

        ``written`` is where a stub's implementation puts the names the stub
        declares, so that a record parsed out of a ``.pyi`` points at real
        source rather than at the stub.
        """
        written = written or {}
        tree = tolerant_parse(info.text)
        scope = ScopeBuilder(self, info, tree, info.text.count("\n") + 1, written).build()
        site = relocate(self._site(info.name, info.path, ast.get_docstring(tree) or ""),
                        written.get(info.name))
        module = SourceModule(scope, site, exported_names(tree),
                              lambda: self.modules(info.name))
        return Analysis(tree, module, info)

    def _resolve(self, dotted: str) -> Value | None:
        path = self._source_path(dotted)
        if path is not None:
            return self.analyse(path, read(path)).module
        directory = self.root.joinpath(*dotted.split("."))
        if directory.is_dir():
            return self._namespace(dotted, directory)
        return self._stdlib(dotted)

    def _declared(self, dotted: str, runtime: Value | None) -> Value | None:
        """``runtime`` as its ``.pyi`` stub describes it, when the project ships one."""
        stub = self._stub(dotted, runtime)
        if stub is None:
            return runtime
        return Stubbed(stub, runtime) if runtime is not None else stub

    def _stub(self, dotted: str, runtime: Value | None) -> Value | None:
        """The module a stub declares for ``dotted``, parsed under its real name."""
        if dotted not in self._stubs:
            self._stubs[dotted] = None  # what a stub importing itself sees
            path = stub_path(self.root, dotted)
            if path is not None:
                info = ModuleInfo(dotted, path.relative_to(self.root).as_posix(), read(path))
                self._stubs[dotted] = self._parse(info, implemented(runtime)).module
        return self._stubs[dotted]

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


def _is_source(relative: Path) -> bool:
    """Files kept in a hidden or cache directory are not the project's own."""
    return not any(part.startswith(".") or part == "__pycache__" for part in relative.parts)


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
