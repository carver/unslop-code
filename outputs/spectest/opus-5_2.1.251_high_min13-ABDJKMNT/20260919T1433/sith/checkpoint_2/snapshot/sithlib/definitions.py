"""The definition records returned by `infer` and `goto`.

A :class:`Definition` names one place a name is defined together with what is
defined there. Values and bindings build their own records; this module owns
the record itself, the way a statement is summarised, and the JSON document.
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from typing import Iterable

BUILTINS = "builtins"

DOCUMENTED = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass(frozen=True)
class Definition:
    """One place a name is defined, and what is defined there."""

    name: str
    type: str
    full_name: str
    module_path: str
    line: int
    column: int
    description: str
    docstring: str = ""


def payload(definitions: Iterable[Definition]) -> str:
    """The JSON document written to standard output."""
    ordered = sorted(dict.fromkeys(definitions), key=position)
    return json.dumps(
        {"definitions": [asdict(definition) for definition in ordered]},
        separators=(",", ":"),
    ) + "\n"


def position(definition: Definition):
    """Sort key: module path, then line, then column."""
    return definition.module_path, definition.line, definition.column


def qualified(*parts: str) -> str:
    """A dotted name built from the parts that are present."""
    return ".".join(part for part in parts if part)


def docstring_of(node: ast.AST) -> str:
    """The docstring of a definition, empty for statements that cannot hold one."""
    if not isinstance(node, DOCUMENTED):
        return ""
    return ast.get_docstring(node) or ""


def describe(node: ast.AST) -> str:
    """How the statement that binds a name is summarised."""
    describer = DESCRIBERS.get(type(node))
    return describer(node) if describer is not None else header(node)


def header(node: ast.AST) -> str:
    """The first line of a statement, without the block it introduces."""
    return ast.unparse(node).split("\n", 1)[0]


def _signature(node) -> str:
    """A function definition, written out with its parameter list."""
    return f"def {node.name}({ast.unparse(node.args)})"


def _assigned(node) -> str:
    """The right-hand side of an assignment, or the statement when it has none."""
    return ast.unparse(node.value) if node.value is not None else ast.unparse(node)


DESCRIBERS = {
    ast.FunctionDef: _signature,
    ast.AsyncFunctionDef: _signature,
    ast.ClassDef: lambda node: f"class {node.name}",
    ast.Import: ast.unparse,
    ast.ImportFrom: ast.unparse,
    ast.Assign: lambda node: ast.unparse(node.value),
    ast.AnnAssign: _assigned,
    ast.arg: lambda node: f"param {node.arg}",
}
