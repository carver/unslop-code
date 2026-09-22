"""The record shared by every completion source.

A :class:`Symbol` is a name the tool can offer, together with enough
information to describe it and to resolve a dot typed after it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
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
    """A completable name and what it refers to."""

    name: str
    kind: str = STATEMENT
    lineno: int = 0
    label: str = ""
    """Type name shown by instance descriptions."""
    value: Optional["Value"] = None
    """Resolved value, used when a dot follows the name."""

    @property
    def description(self) -> str:
        return DESCRIPTIONS[self.kind].format(name=self.name, label=self.label)


def from_value(name: str, lineno: int, value: Optional["Value"]) -> Symbol:
    """Describe a binding of ``name`` to an inferred ``value``."""
    if value is None:
        return Symbol(name, STATEMENT, lineno)
    return Symbol(name, value.kind, lineno, value.label, value)
