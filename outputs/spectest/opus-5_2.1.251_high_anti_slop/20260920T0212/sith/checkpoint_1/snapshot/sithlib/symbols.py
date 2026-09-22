"""The completion candidates produced by analysis, and how they are ordered."""

from dataclasses import dataclass, field

MODULE = "module"
CLASS = "class"
FUNCTION = "function"
INSTANCE = "instance"
STATEMENT = "statement"
PARAM = "param"
KEYWORD = "keyword"

_PUBLIC, _PRIVATE, _DUNDER, _KEYWORD = range(4)


@dataclass(frozen=True)
class Symbol:
    """A name that can be completed, plus what is statically known about it.

    `type_name` is the name of the type the symbol holds (``x = Foo()`` gives
    ``Foo``). It drives attribute resolution and never reaches the output.
    """

    name: str
    kind: str
    description: str
    lineno: int = 0
    type_name: str = field(default=None, compare=False)


def module(name, lineno=0):
    return Symbol(name, MODULE, f"module {name}", lineno)


def klass(name, lineno=0):
    return Symbol(name, CLASS, f"class {name}", lineno, type_name=name)


def function(name, lineno=0):
    return Symbol(name, FUNCTION, f"def {name}(...)", lineno)


def instance(name, type_name, lineno=0):
    return Symbol(name, INSTANCE, f"instance of {type_name}", lineno, type_name=type_name)


def statement(name, lineno=0):
    return Symbol(name, STATEMENT, "statement", lineno)


def param(name, lineno=0, type_name=None):
    return Symbol(name, PARAM, "param", lineno, type_name=type_name)


def keyword(name):
    return Symbol(name, KEYWORD, name)


def _group(symbol):
    if symbol.kind == KEYWORD:
        return _KEYWORD
    if symbol.name.startswith("__") and symbol.name.endswith("__"):
        return _DUNDER
    if symbol.name.startswith("_"):
        return _PRIVATE
    return _PUBLIC


def sort_key(symbol):
    """Public names, then private, then dunders, then keywords; alphabetical within."""
    return (_group(symbol), symbol.name.lower())


def as_completion(symbol, prefix_length):
    """Render a symbol as the JSON object the CLI emits."""
    return {
        "name": symbol.name,
        "complete": symbol.name[prefix_length:],
        "type": symbol.kind,
        "description": symbol.description,
    }
