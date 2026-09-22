"""What the cursor is asking for: a bare name or an attribute of something."""

from __future__ import annotations

import string
from dataclasses import dataclass

from .source import indent_of

NAME = "name"
ATTRIBUTE = "attribute"

IDENTIFIER_CHARS = set(string.ascii_letters + string.digits + "_")
CLOSERS = {")": "(", "]": "[", "}": "{"}
QUOTES = "\"'"


@dataclass
class Context:
    """The completion request described by a cursor position."""

    kind: str
    prefix: str
    receiver: str = ""
    """Source text of the expression before the dot, for attribute contexts."""
    indent: int = 0
    """Indentation the cursor sits at, used to place it in a scope."""


def context_at(text: str, col: int) -> Context:
    """Read the completion context out of a line of source and a column."""
    start = col
    while start > 0 and text[start - 1] in IDENTIFIER_CHARS:
        start -= 1
    prefix = text[start:col]
    indent = cursor_indent(text, col)
    if start > 0 and text[start - 1] == ".":
        dot = start - 1
        return Context(ATTRIBUTE, prefix, text[expression_start(text, dot):dot], indent)
    return Context(NAME, prefix, indent=indent)


def cursor_indent(text: str, col: int) -> int:
    """Indentation of the cursor: its own column when nothing precedes it."""
    if text[:col].strip():
        return indent_of(text)
    return col


def expression_start(text: str, end: int) -> int:
    """Index where the primary expression ending at ``end`` begins.

    Walks back over names, dots, bracketed groups and string literals, which
    is enough to cover receivers such as ``a.b[0]`` or ``"text"``.
    """
    index = end
    while index > 0:
        char = text[index - 1]
        if char in CLOSERS:
            index = _matching_open(text, index - 1)
        elif char in QUOTES:
            index = text.rfind(char, 0, index - 1)
        elif char in IDENTIFIER_CHARS or char == ".":
            index -= 1
            continue
        else:
            break
        if index < 0:
            return end
    return index


def _matching_open(text: str, index: int) -> int:
    """Index of the bracket opening the group closed at ``index``."""
    closer = text[index]
    opener = CLOSERS[closer]
    depth = 0
    for position in range(index, -1, -1):
        if text[position] == closer:
            depth += 1
        elif text[position] == opener:
            depth -= 1
            if depth == 0:
                return position
    return -1
