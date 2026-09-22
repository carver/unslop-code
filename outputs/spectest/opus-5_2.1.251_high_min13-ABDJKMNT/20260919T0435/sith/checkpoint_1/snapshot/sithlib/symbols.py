"""Completion records and the descriptions attached to them."""

from __future__ import annotations

import inspect
from dataclasses import dataclass

MODULE = "module"
CLASS = "class"
FUNCTION = "function"
INSTANCE = "instance"
STATEMENT = "statement"
PARAM = "param"
KEYWORD = "keyword"

_DESCRIPTIONS = {
    MODULE: "module {name}",
    CLASS: "class {name}",
    FUNCTION: "def {name}(...)",
    INSTANCE: "instance of {type_name}",
    PARAM: "param {name}",
    KEYWORD: "{name}",
    STATEMENT: "statement",
}

_RUNTIME_KINDS = (
    (inspect.ismodule, MODULE),
    (inspect.isclass, CLASS),
    (inspect.isroutine, FUNCTION),
)


def describe(kind: str, name: str, type_name: str | None = None) -> str:
    return _DESCRIPTIONS[kind].format(name=name, type_name=type_name)


def classify(obj: object) -> str:
    """The completion `type` of a live Python object."""
    return next((kind for test, kind in _RUNTIME_KINDS if test(obj)), INSTANCE)


@dataclass(frozen=True)
class Symbol:
    """One completion candidate before prefix filtering and ordering."""

    name: str
    kind: str
    description: str

    @classmethod
    def of(cls, name: str, kind: str, type_name: str | None = None) -> "Symbol":
        return cls(name, kind, describe(kind, name, type_name))

    @classmethod
    def from_object(cls, name: str, obj: object) -> "Symbol":
        kind = classify(obj)
        return cls.of(name, kind, type(obj).__name__)
