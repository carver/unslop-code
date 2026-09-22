"""Paths as they appear in output: relative to the project root, POSIX-separated."""

from __future__ import annotations

import os


def posix(path: str) -> str:
    """A filesystem path written with forward slashes, whatever the host uses."""
    return path.replace(os.sep, "/") if os.sep != "/" else path


def relative(path: str, root: str) -> str:
    """`path` seen from the project root, or left absolute when it lies outside it."""
    relative_path = os.path.relpath(path, root)
    return posix(path if relative_path.startswith(os.pardir) else relative_path)


def qualified_name(path: str, root: str) -> str:
    """The dotted module name of a file inside the project root.

    `pkg/tools.py` is `pkg.tools` and `pkg/__init__.py` is the package `pkg`
    itself.  A file outside the root has no qualified name beyond its own stem.
    """
    relative_path = relative(path, root).removesuffix(".py")
    if relative_path.startswith("/") or relative_path.startswith(".."):
        return os.path.basename(relative_path)
    parts = relative_path.split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)
