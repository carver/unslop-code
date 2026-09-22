"""The record shared by every completion source.

A :class:`Symbol` is a name the tool can offer, together with enough
information to describe it, to resolve a dot typed after it, and to say where
the binding was written.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .analysis import Analyzer
    from .runtime import Value

MODULE = "module"
CLASS = "class"
FUNCTION = "function"
INSTANCE = "instance"
STATEMENT = "statement"
PARAM = "param"
KEYWORD = "keyword"

DESCRIPTIONS = {
    MODULE: "module {name}",
    CLASS: "class {name}",
    FUNCTION: "def {name}(...)",
    INSTANCE: "instance of {label}",
    STATEMENT: "statement",
    PARAM: "param {name}",
    KEYWORD: "{name}",
}


@dataclass
class Symbol:
    """A completable name, what it refers to, and where it was bound."""

    name: str
    kind: str = STATEMENT
    lineno: int = 0
    label: str = ""
    """Type name shown by instance descriptions."""
    value: Optional["Value"] = None
    """Resolved value, used when a dot follows the name."""
    column: int = 0
    node: Optional[ast.AST] = None
    """Statement that binds the name, for `goto`."""
    origin: Optional["Analyzer"] = None
    """File the binding was written in."""
    qualifier: str = ""
    """Dotted names of the definitions enclosing the binding."""
    conditional: bool = False
    """Whether the binding sits in a branch that may not have run."""

    @property
    def description(self) -> str:
        return DESCRIPTIONS[self.kind].format(name=self.name, label=self.label)


def from_value(name: str, lineno: int, value: Optional["Value"], **placement) -> Symbol:
    """Describe a binding of ``name`` to an inferred ``value``."""
    if value is None:
        return Symbol(name, STATEMENT, lineno, **placement)
    return Symbol(name, value.kind, lineno, value.label, value, **placement)
