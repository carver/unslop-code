"""The definition records that `infer` and `goto` answer with."""

from __future__ import annotations

import ast
import inspect
import re
from dataclasses import dataclass

from . import paths
from .symbols import INSTANCE, MODULE, describe

BUILTINS = "builtins"


@dataclass(frozen=True)
class Definition:
    """One place a name is defined, or one type it evaluates to."""

    name: str
    kind: str
    full_name: str
    module_path: str
    line: int
    column: int
    description: str
    docstring: str = ""

    @property
    def order(self) -> tuple[str, int, int]:
        return (self.module_path, self.line, self.column)

    def as_dict(self, docstring: bool = True) -> dict:
        """The JSON record; `search` results are the same fields without the docstring."""
        record = {
            "name": self.name,
            "type": self.kind,
            "full_name": self.full_name,
            "module_path": self.module_path,
            "line": self.line,
            "column": self.column,
            "description": self.description,
        }
        return {**record, "docstring": self.docstring} if docstring else record


def render(found: list[Definition]) -> list[dict]:
    """Drop duplicates and sort by `(module_path, line, column)` for output."""
    unique = list(dict.fromkeys(found))
    return [definition.as_dict() for definition in sorted(unique, key=lambda d: d.order)]


def name_column(lines: list[str], node: ast.AST, name: str) -> int:
    """Column of the `name` identifier inside the statement that defines it.

    The node of a `def`, a `class` or an `import` starts at its keyword, so the
    identifier is looked up in the source text rather than taken from the node.
    """
    return column_after(lines, node.lineno, node.col_offset, name)


def column_after(lines: list[str], line: int, column: int, name: str) -> int:
    """Column of the first `name` identifier written at or after a position."""
    text = lines[line - 1] if line <= len(lines) else ""
    found = re.compile(rf"\b{re.escape(name)}\b").search(text, column)
    return found.start() if found else column


def function_description(node: ast.AST) -> str:
    """`def name(params)`, with the parameters written as in the source."""
    return f"def {node.name}({ast.unparse(node.args)})"


def docstring_of(node: ast.AST) -> str:
    return ast.get_docstring(node) or ""


def builtin(name: str, kind: str = INSTANCE) -> Definition:
    """A definition for a builtin type, which has no source location."""
    return Definition(
        name=name,
        kind=kind,
        full_name=f"{BUILTINS}.{name}",
        module_path="",
        line=0,
        column=0,
        description=describe(kind, name, name),
    )


def module(full_name: str, path: str, docstring: str = "") -> Definition:
    """A definition for a module, which has no identifier to point at."""
    name = full_name.rsplit(".", 1)[-1]
    return Definition(
        name=name,
        kind=MODULE,
        full_name=full_name,
        module_path=path,
        line=0,
        column=0,
        description=describe(MODULE, name),
        docstring=docstring,
    )


def imported_module(full_name: str, obj: object) -> Definition:
    """A definition for a module that had to be imported to be read."""
    path, _ = source_location(obj)
    return module(full_name, path, inspect.getdoc(obj) or "" if path else "")


def from_object(name: str, obj: object, kind: str, description: str) -> Definition:
    """A definition for a live object, located by inspection where possible."""
    owner = getattr(obj, "__module__", None)
    qualified = getattr(obj, "__qualname__", name)
    path, line = source_location(obj)
    return Definition(
        name=name,
        kind=kind,
        full_name=f"{owner}.{qualified}" if owner else qualified,
        module_path=path,
        line=line,
        column=0,
        description=description,
        docstring=inspect.getdoc(obj) or "" if path else "",
    )


def type_name(cls: type) -> str:
    """What a builtin type is called in a definition; `None` keeps its literal name."""
    return "None" if cls is type(None) else cls.__name__


def source_location(obj: object) -> tuple[str, int]:
    """The file and line an object was defined at, or no location at all."""
    try:
        return paths.posix(inspect.getsourcefile(obj) or ""), inspect.getsourcelines(obj)[1]
    except (TypeError, OSError):
        # Builtins and C extensions carry no source; the spec asks for a record
        # without a location rather than no record at all.
        return "", 0
