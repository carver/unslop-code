"""Reading import statements: what they name and what they export.

Nothing here touches the filesystem.  It turns the syntax of an import into
the dotted name :mod:`sithlib.project` should look up, and recognises an
unfinished import under a cursor so that completion knows what is being asked
for.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

# ``a, b as c,`` -- the aliases already listed before the one being typed.
_LISTED = r"(?:[\w.]+(?:\s+as\s+\w+)?\s*,\s*)*"
_CLAUSE = re.compile(rf"^\s*from\s+(?P<dots>\.*)(?P<module>[\w.]*?)\s+import\s+{_LISTED}$")
_PATH = re.compile(rf"^\s*(?:import|from)\s+{_LISTED}(?P<dots>\.*)(?P<module>[\w.]*\.)?$")


@dataclass(frozen=True)
class ImportContext:
    """The unfinished import statement a cursor sits in.

    ``names`` distinguishes the two halves of ``from x import y``: the module
    path, where the modules themselves are wanted, from the import clause,
    where the names inside the module are.  ``level`` counts the leading dots
    of a relative import.
    """

    module: str
    level: int
    names: bool


def context(text: str) -> ImportContext | None:
    """The import a cursor is in, given its line up to the name being typed."""
    clause = _CLAUSE.match(text)
    if clause is not None:
        return ImportContext(clause["module"], len(clause["dots"]), True)
    path = _PATH.match(text)
    if path is None:
        return None
    return ImportContext((path["module"] or "").rstrip("."), len(path["dots"]), False)


def absolute(module: str, level: int, package: str) -> str | None:
    """The dotted name an import names, or ``None`` if it reaches above the root.

    ``package`` is the package the importing module sits in, which is empty for
    a module at the project root.  The root itself counts as a package, so
    ``from . import x`` written there names ``x``.
    """
    if not level:
        return module
    parts = package.split(".") if package else []
    if level > len(parts) + 1:
        return None
    return ".".join(parts[:len(parts) - level + 1] + ([module] if module else []))


def qualified(prefix: str, name: str) -> str:
    """``name`` under dotted ``prefix``; an empty prefix is the project root."""
    return f"{prefix}.{name}" if prefix else name


def exported_names(tree: ast.Module) -> tuple[str, ...] | None:
    """The names ``__all__`` declares, or ``None`` when the module declares none."""
    for statement in tree.body:
        match statement:
            case (ast.Assign(targets=[ast.Name(id="__all__")], value=value)
                  | ast.AnnAssign(target=ast.Name(id="__all__"), value=ast.expr() as value)):
                return _strings(value)
    return None


def _strings(value: ast.expr) -> tuple[str, ...]:
    """The string literals of a list or tuple display, ignoring anything else."""
    elements = value.elts if isinstance(value, (ast.List, ast.Tuple)) else []
    return tuple(element.value for element in elements
                 if isinstance(element, ast.Constant) and isinstance(element.value, str))
