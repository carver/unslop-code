"""The scopes a cursor sits inside.

Where completion asks what a line can see, this asks what it belongs to: the
classes and functions written around it, outermost first.  A cursor at module
level belongs to nothing and reports nothing.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass

from .cursor import name_column

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass(frozen=True)
class ScopeContext:
    """One class or function the cursor is written inside."""

    name: str
    type: str
    line: int
    column: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def enclosing(tree: ast.Module, line: int) -> list[ScopeContext]:
    """The definitions holding ``line``, from the outermost one inwards.

    Scopes that contain the same line are nested in one another, so ordering
    them by the line they start on orders them from outside in.
    """
    holding = [node for node in ast.walk(tree)
               if isinstance(node, _SCOPES) and node.lineno <= line <= node.end_lineno]
    return [ScopeContext(node.name, _kind(node), node.lineno, name_column(node))
            for node in sorted(holding, key=lambda node: node.lineno)]


def _kind(node: ast.AST) -> str:
    return "class" if isinstance(node, ast.ClassDef) else "function"
