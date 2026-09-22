"""Module resolution for the directory the analysed file lives in."""

from __future__ import annotations

import ast
import importlib
from dataclasses import dataclass
from pathlib import Path

from .builder import ScopeBuilder
from .definitions import Definition
from .parsing import tolerant_parse
from .values import RuntimeObject, SourceModule, Value


@dataclass(frozen=True)
class ModuleInfo:
    """Which file is being analysed, under which name, with which text."""

    name: str
    path: str
    text: str


@dataclass(frozen=True)
class Analysis:
    """A parsed file: the tree a cursor is located in and the module it binds."""

    tree: ast.Module
    module: SourceModule


class Project:
    """Maps a dotted module name onto a value.

    Modules that exist as files next to the analysed file are parsed rather
    than imported, which keeps project code from being executed; everything
    else falls back to a real import so installed packages still resolve.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._resolved: dict[str, Value | None] = {}
        self._active: set[str] = set()

    def analyse(self, path: Path, dotted: str, text: str) -> Analysis:
        """Parse ``path`` and record every name its module body binds."""
        tree = tolerant_parse(text)
        info = ModuleInfo(dotted, self._relative(path), text)
        scope = ScopeBuilder(self, info).build(tree, text.count("\n") + 1)
        site = Definition(dotted.split(".")[-1], "module", dotted, info.path, 1, 0,
                          f"module {dotted}", ast.get_docstring(tree) or "")
        return Analysis(tree, SourceModule(scope, site))

    def module(self, dotted: str, level: int = 0) -> Value | None:
        """The value of module ``dotted``, or ``None`` if it cannot be found."""
        if not dotted:
            return None
        key = "." * level + dotted
        if key not in self._resolved:
            if key in self._active:
                return None  # circular import between project modules
            self._active.add(key)
            try:
                self._resolved[key] = self._resolve(dotted, level)
            finally:
                self._active.discard(key)
        return self._resolved[key]

    def _resolve(self, dotted: str, level: int) -> Value | None:
        path = self._source_path(dotted)
        if path is not None:
            text = path.read_text(encoding="utf-8", errors="replace")
            return self.analyse(path, dotted, text).module
        if level:
            return None  # an explicit relative import never names an installed package
        return self._installed(dotted)

    def _source_path(self, dotted: str) -> Path | None:
        parts = dotted.split(".")
        candidates = (self.root.joinpath(*parts).with_suffix(".py"),
                      self.root.joinpath(*parts, "__init__.py"))
        return next((path for path in candidates if path.is_file()), None)

    def _relative(self, path: Path) -> str:
        """The path of a project file as it is reported, relative to the root."""
        return path.resolve().relative_to(self.root).as_posix()

    def _installed(self, dotted: str) -> Value | None:
        try:
            module = importlib.import_module(dotted)
        except Exception:
            # Importing third party code runs it, and it may fail in any way;
            # an unresolvable module simply offers no completions.
            return None
        return RuntimeObject(module, dotted.rsplit(".", 1)[-1], "module",
                             f"module {dotted}", public_only=True)
