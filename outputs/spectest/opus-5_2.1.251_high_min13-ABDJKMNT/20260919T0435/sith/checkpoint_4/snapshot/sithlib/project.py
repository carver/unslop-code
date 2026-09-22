"""The files a project-wide request has to read."""

from __future__ import annotations

import os

from . import paths, resolve
from .modules import ModuleIndex

SKIPPED = {"__pycache__"}


def python_files(root: str) -> list[str]:
    """Every `.py` file under the project root, in a stable order."""
    found = []
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = sorted(
            name for name in subdirectories if name not in SKIPPED and not name.startswith(".")
        )
        found += [os.path.join(directory, name) for name in sorted(names) if name.endswith(".py")]
    return found


def modules(root: str, follow: bool = False):
    """Yield `(resolver, tree)` for each module of the project, sharing one index.

    Resolvers built here carry no cursor position, so a name resolves the same
    way wherever in the file it was written.
    """
    index = ModuleIndex(root)
    siblings: dict = {}
    for path in python_files(root):
        handle = index.resolve(paths.qualified_name(path, root))
        if handle is not None:
            yield resolve.for_module(handle, index, siblings, follow)


def root_of(path: str, project: str | None) -> str:
    """The project root of a request, which defaults to the file's own directory."""
    return os.path.abspath(project) if project else os.path.dirname(os.path.abspath(path))
