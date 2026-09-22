"""The files a project-wide request has to read."""

from __future__ import annotations

import os

from . import paths, resolve
from .modules import ModuleIndex
from .settings import Settings

SKIPPED = {"__pycache__"}
PACKAGE_FILE = "__init__.py"


def _walk(root: str):
    """Every readable directory under the root and its file names, in a stable order."""
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = sorted(
            name for name in subdirectories if name not in SKIPPED and not name.startswith(".")
        )
        yield directory, sorted(names)


def python_files(root: str) -> list[str]:
    """Every `.py` file under the project root, in a stable order."""
    return [
        os.path.join(directory, name)
        for directory, names in _walk(root)
        for name in names
        if name.endswith(".py")
    ]


def import_roots(root: str) -> list[str]:
    """What `smart_sys_path` detects: the project root and its package directories."""
    packages = [
        directory
        for directory, names in _walk(root)
        if directory != root and PACKAGE_FILE in names
    ]
    return [root, *packages]


def modules(root: str, follow: bool = False, index: ModuleIndex | None = None,
            settings: Settings | None = None):
    """Yield `(resolver, tree)` for each module of the project, sharing one index.

    Resolvers built here carry no cursor position, so a name resolves the same
    way wherever in the file it was written.
    """
    index = index or ModuleIndex(root)
    siblings: dict = {}
    for path in python_files(root):
        handle = index.resolve(paths.qualified_name(path, root))
        if handle is not None:
            yield resolve.for_module(handle, index, siblings, follow, settings or Settings())


def root_of(path: str, project: str | None) -> str:
    """The project root of a request, which defaults to the file's own directory."""
    return os.path.abspath(project) if project else os.path.dirname(os.path.abspath(path))
