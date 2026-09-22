"""The project a file is analysed in: module search and the analysis cache.

Imports are resolved from the project's import roots first and from the
standard library second; project files are parsed, never imported. One
analysis is kept per file, so a cycle of imports meets an analysis already
under way rather than starting another one.
"""

from __future__ import annotations

import ast
import functools
import inspect
import pkgutil
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .analysis import Analyzer, SourceModule
from .configuration import ProjectConfig, load_config
from .definitions import qualified
from .importing import package_above, written_path
from .namespaces import Namespaces
from .runtime import RuntimeValue, Value, import_module
from .settings import Settings
from .source import Source
from .stubs import Stubbed, stub_candidates
from .symbols import MODULE, Symbol

INIT = "__init__.py"
SKIPPED = {"__pycache__"}


class Project:
    """The root imports are resolved against, and the files below it.

    The configuration file the root carries decides how imports are resolved
    and which settings the analysis runs with; `--setting` flags, passed as
    ``overrides``, have the last word.
    """

    def __init__(self, root, overrides=None, namespaces: Optional[Namespaces] = None):
        self.root = Path(root)
        self.config = load_config(self.root)
        self.settings = Settings(
            smart_sys_path=self.config.smart_sys_path
        ).with_overrides(overrides or {})
        self.namespaces = namespaces if namespaces is not None else Namespaces()
        self._analyzers: Dict[Path, Analyzer] = {}

    @functools.cached_property
    def search_paths(self) -> List[Path]:
        """The directories imports are resolved against, in search order."""
        return search_paths(self.root, self.config, self.settings.smart_sys_path)

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

    def project_module(self, dotted: str) -> Optional[Value]:
        """The module a dotted name names among the project's own files.

        A module a stub describes answers with both files: the stub for the
        types it declares and the module itself for everything else.
        """
        path = self.file_of(dotted)
        stub = self.stub_of(dotted)
        described = SourceModule(self.analyzer_at(stub)) if stub is not None else None
        if path is None:
            return described
        module = SourceModule(self.analyzer_at(path))
        return Stubbed(described, module) if described is not None else module

    def stub_of(self, dotted: str) -> Optional[Path]:
        """The stub file carrying a module's type information, if it has one."""
        if not dotted:
            return None
        return next(
            (path
             for root in self.search_paths
             for path in stub_candidates(root, dotted)
             if path.is_file()),
            None,
        )

    def files(self) -> List[Path]:
        """Every Python source file in the project, in path order."""
        return sorted(
            path for path in self.root.rglob("*.py") if not _is_hidden(path.relative_to(self.root))
        )

    def file_of(self, dotted: str) -> Optional[Path]:
        """The file a dotted name names, searching each import root in turn."""
        found = (module_file(root, dotted) for root in self.search_paths)
        return next((path for path in found if path is not None), None)

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


def search_paths(root: Path, config: ProjectConfig, smart: bool) -> List[Path]:
    """The directories imports are resolved against, in search order.

    An explicit `sys_path` replaces what the project would detect on its own,
    and `added_sys_path` is appended to whichever of the two is in force. A
    relative entry is read from the project root, the way it is written.
    """
    if config.sys_path:
        detected = [root / entry for entry in config.sys_path]
    else:
        detected = [root, *package_directories(root)] if smart else []
    return detected + [root / entry for entry in config.added_sys_path]


def package_directories(root: Path) -> List[Path]:
    """Directories of the project that hold an `__init__.py`."""
    return sorted(
        path.parent for path in root.rglob(INIT) if not _is_hidden(path.relative_to(root))
    )


def module_file(root: Path, dotted: str) -> Optional[Path]:
    """The file a dotted name names below one root, namespace packages included.

    Packages win over modules of the same name, as they do at runtime, and a
    directory with no `__init__.py` is a namespace package.
    """
    located = root.joinpath(*dotted.split(".")) if dotted else root
    if (located / INIT).is_file():
        return located / INIT
    if dotted and located.with_suffix(".py").is_file():
        return located.with_suffix(".py")
    return located if _is_namespace(located) else None


def _source_at(path: Path) -> Source:
    """The source of a project module; a namespace package has none."""
    if path.is_dir():
        return Source(path, [], ast.Module(body=[], type_ignores=[]))
    return Source.load(path)


def _is_hidden(relative: Path) -> bool:
    """Whether a path lies in a directory the project does not analyse."""
    return any(part in SKIPPED or part.startswith(".") for part in relative.parts)


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
