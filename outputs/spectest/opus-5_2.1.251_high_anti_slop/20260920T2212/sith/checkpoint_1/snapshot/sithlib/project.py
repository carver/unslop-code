"""Module resolution for the directory the analysed file lives in."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from .builder import ScopeBuilder
from .parsing import tolerant_parse
from .scopes import Scope
from .values import RuntimeObject, SourceModule, Value


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

    def build(self, tree: ast.Module, last_line: int) -> Scope:
        """The scope tree of the file under the cursor."""
        return ScopeBuilder(self).build(tree, last_line)

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
            return SourceModule(self._analyse(path), dotted)
        if level:
            return None  # an explicit relative import never names an installed package
        return self._installed(dotted)

    def _source_path(self, dotted: str) -> Path | None:
        parts = dotted.split(".")
        candidates = (self.root.joinpath(*parts).with_suffix(".py"),
                      self.root.joinpath(*parts, "__init__.py"))
        return next((path for path in candidates if path.is_file()), None)

    def _analyse(self, path: Path) -> Scope:
        text = path.read_text(encoding="utf-8", errors="replace")
        return ScopeBuilder(self).build(tolerant_parse(text), text.count("\n") + 1)

    def _installed(self, dotted: str) -> Value | None:
        try:
            module = importlib.import_module(dotted)
        except Exception:
            # Importing third party code runs it, and it may fail in any way;
            # an unresolvable module simply offers no completions.
            return None
        return RuntimeObject(module, "module", f"module {dotted}", public_only=True)
