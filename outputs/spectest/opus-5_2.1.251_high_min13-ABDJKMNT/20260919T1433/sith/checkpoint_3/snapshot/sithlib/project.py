"""The project a file is analysed in: module search and the analysis cache.

Imports are resolved from the project root first and from the standard library
second; project files are parsed, never imported. One analysis is kept per
file, so a cycle of imports meets an analysis already under way rather than
starting another one.
"""

from __future__ import annotations

import ast
import inspect
import pkgutil
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .analysis import Analyzer, SourceModule
from .definitions import qualified
from .importing import package_above, written_path
from .runtime import RuntimeValue, Value, import_module
from .source import Source
from .symbols import MODULE, Symbol

INIT = "__init__.py"
SKIPPED = {"__pycache__"}


class Project:
    """The root imports are resolved against, and the files below it."""

    def __init__(self, root):
        self.root = Path(root)
        self._analyzers: Dict[Path, Analyzer] = {}

    # -- analysed files ----------------------------------------------------

    def analyzer_for(self, source: Source) -> Analyzer:
        """The analysis of a file that is already loaded.

        Keeping one analysis per file is what stops a cycle of imports: the
        second file to import the first meets an analysis already under way
        and sees the bindings made so far.
        """
        key = source.path.resolve()
        if key not in self._analyzers:
            self._analyzers[key] = Analyzer(source, self)
        return self._analyzers[key]

    def analyzer_at(self, path: Path) -> Analyzer:
        """The analysis of a project file, read from disk the first time."""
        analyzed = self._analyzers.get(path.resolve())
        return analyzed if analyzed is not None else self.analyzer_for(_source_at(path))

    # -- module search -----------------------------------------------------

    def module(self, dotted: str) -> Optional[Value]:
        """The module a dotted name names: project first, standard library next."""
        found = self.project_module(dotted)
        if found is not None:
            return found
        installed = import_module(dotted) if is_stdlib(dotted) else None
        return RuntimeValue(installed) if installed is not None else None

    def module_for(self, analyzer: Analyzer, level: int, dotted: str) -> Optional[Value]:
        """The module an import statement names, relative or absolute.

        A relative path is counted from the importing module's package and
        stays inside the project, so it never reaches the standard library.
        """
        if not level:
            return self.module(dotted)
        base = package_above(analyzer.package, level)
        return self.project_module(qualified(base, dotted)) if base is not None else None

    def project_module(self, dotted: str) -> Optional[SourceModule]:
        """The module a dotted name names among the project's own files."""
        path = self.file_of(dotted)
        return SourceModule(self.analyzer_at(path)) if path is not None else None

    def file_of(self, dotted: str) -> Optional[Path]:
        """The file a dotted name names, or the directory of a namespace package.

        Packages win over modules of the same name, as they do at runtime, and
        a directory with no `__init__.py` is a namespace package.
        """
        located = self.root.joinpath(*dotted.split(".")) if dotted else self.root
        if (located / INIT).is_file():
            return located / INIT
        if dotted and located.with_suffix(".py").is_file():
            return located.with_suffix(".py")
        return located if _is_namespace(located) else None

    # -- names offered inside an import statement --------------------------

    def module_names(self, analyzer: Analyzer, text: str) -> List[Symbol]:
        """The module names that can follow the import path written so far."""
        level, dotted = written_path(text)
        if level:
            base = package_above(analyzer.package, level)
            return self._contained(qualified(base, dotted)) if base is not None else []
        if dotted:
            return self._contained(dotted) + _runtime_submodules(dotted)
        return _module_symbols(_entries(self.root)) + _module_symbols(sys.stdlib_module_names)

    def _contained(self, dotted: str) -> List[Symbol]:
        """Module names inside a project package, without analysing them."""
        return _module_symbols(_entries(_directory_of(self.file_of(dotted))))

    def submodules(self, path: Path) -> List[Symbol]:
        """The modules a package contains, as bindings of that package."""
        return [
            Symbol(name, MODULE, value=SourceModule(self.analyzer_at(child)))
            for name, child in sorted(_entries(_directory_of(path)).items())
        ]


def _source_at(path: Path) -> Source:
    """The source of a project module; a namespace package has none."""
    if path.is_dir():
        return Source(path, [], ast.Module(body=[], type_ignores=[]))
    return Source.load(path)


def _is_namespace(path: Path) -> bool:
    """Whether a directory can be imported as a namespace package."""
    return path.is_dir() and path.name not in SKIPPED and not path.name.startswith(".")


def _directory_of(path: Optional[Path]) -> Optional[Path]:
    """The directory a package's modules live in; a plain module has none."""
    if path is not None and path.name == INIT:
        return path.parent
    return path if path is not None and path.is_dir() else None


def _entries(directory: Optional[Path]) -> Dict[str, Path]:
    """Importable children of a directory, keyed by the name they import as."""
    found: Dict[str, Path] = {}
    for child in sorted(directory.iterdir()) if directory is not None else []:
        name = child.stem if child.suffix == ".py" else child.name
        if name in SKIPPED or name == "__init__" or not name.isidentifier():
            continue
        if child.is_dir():
            found[name] = child / INIT if (child / INIT).is_file() else child
        elif child.suffix == ".py":
            found.setdefault(name, child)
    return found


def _module_symbols(names: Iterable[str]) -> List[Symbol]:
    """Module names offered as completions, with no file read to describe them."""
    return [Symbol(name, MODULE) for name in names]


def _runtime_submodules(dotted: str) -> List[Symbol]:
    """The modules an installed package leads to.

    Both the files it contains and the modules it has already pulled in under
    a name of its own, which is how `os.path` is reached.
    """
    package = import_module(dotted) if is_stdlib(dotted) else None
    if package is None:
        return []
    found = {name for name in dir(package) if inspect.ismodule(getattr(package, name, None))}
    found.update(module.name for module in pkgutil.iter_modules(getattr(package, "__path__", [])))
    return _module_symbols(sorted(found))


def is_stdlib(dotted: str) -> bool:
    """Whether a dotted name belongs to a standard library module."""
    return dotted.split(".")[0] in sys.stdlib_module_names
