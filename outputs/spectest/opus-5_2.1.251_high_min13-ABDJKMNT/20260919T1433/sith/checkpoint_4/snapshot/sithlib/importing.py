"""Reading the parts of an import statement.

Only syntax lives here: which name an alias binds, which module it names, and
which package a relative import counts its dots from. Turning those names into
files is :mod:`sithlib.project`'s job.
"""

from __future__ import annotations

import ast
from typing import Optional, Tuple

IMPORT_NODES = (ast.Import, ast.ImportFrom)
STAR = "*"


def bound_name(alias: ast.alias) -> str:
    """The name an import alias binds."""
    return alias.asname or alias.name.split(".")[0]


def imported_module(alias: ast.alias) -> str:
    """The module a plain `import` alias refers to.

    `import a.b` binds `a`, so the binding refers to the root package; an
    `as` clause binds the module the whole dotted path names.
    """
    return alias.name if alias.asname else alias.name.split(".")[0]


def alias_column(alias: ast.alias) -> int:
    """Column of the name an import binds, which an ``as`` clause moves."""
    if alias.asname:
        return alias.end_col_offset - len(alias.asname)
    return alias.col_offset


def alias_for(node: ast.stmt, name: str) -> Optional[ast.alias]:
    """The alias of an import statement that binds ``name``, if any."""
    return next((alias for alias in node.names if bound_name(alias) == name), None)


def package_above(package: str, level: int) -> Optional[str]:
    """The package that ``level`` leading dots reach from ``package``.

    Dots are counted as Python counts them: one dot is the importing module's
    own package. ``None`` means the count runs off the top of the project.
    """
    parts = package.split(".") if package else []
    remaining = len(parts) - (level - 1)
    return ".".join(parts[:remaining]) if remaining >= 0 else None


def written_path(text: str) -> Tuple[int, str]:
    """The level and dotted name of a module path as it is written in source.

    A trailing dot marks a path that is still being typed (`pkg.`), and leading
    dots make the path relative.
    """
    stripped = text.lstrip(".")
    return len(text) - len(stripped), stripped.strip(".")
