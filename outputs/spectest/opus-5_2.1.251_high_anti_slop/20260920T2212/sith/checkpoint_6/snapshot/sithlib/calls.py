"""Finding the call whose argument list a cursor sits in.

The line under a cursor is rarely valid Python -- the call being written
usually has no closing parenthesis yet -- so the call is recovered from the
text rather than from the parse tree: the innermost parenthesis still open at
the cursor, the expression written just before it, and the arguments typed
since.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Iterator

from .source import trailing_expression

# ``def f(`` and ``class C(`` open a parameter list or a base list, not a call.
_DEFINITION = re.compile(r"\b(?:def|class)\s+\w+\s*$")
_KEYWORD = re.compile(r"\s*([A-Za-z_]\w*)\s*=(?!=)")
_OPENING, _CLOSING = "([{", ")]}"


@dataclass(frozen=True)
class CallSite:
    """The unfinished call the cursor is writing arguments for.

    ``position`` counts the positional arguments already supplied, so it is the
    index of the one being typed; ``keyword`` is set instead when the argument
    being typed names its parameter.
    """

    callee: ast.expr
    line: int
    position: int
    keyword: str | None


def call_at(text: str, offset: int) -> CallSite | None:
    """The call whose parentheses hold ``offset``, or ``None`` outside one."""
    head = text[:offset]
    open_brackets = _open_brackets(head)
    if not open_brackets or head[open_brackets[-1]] != "(":
        return None
    paren = open_brackets[-1]
    before = head[:paren].rstrip()
    if _DEFINITION.search(before):
        return None
    callee = trailing_expression(before)
    if callee is None:
        return None
    supplied = _split(head[paren + 1:])
    position = sum(1 for argument in supplied[:-1] if _keyword(argument) is None)
    return CallSite(callee, head.count("\n", 0, paren) + 1, position, _keyword(supplied[-1]))


def _open_brackets(text: str) -> list[int]:
    """The offsets of the brackets still open at the end of ``text``."""
    stack: list[int] = []
    for index, character in _scan(text):
        if character in _OPENING:
            stack.append(index)
        elif character in _CLOSING and stack:
            stack.pop()
    return stack


def _split(region: str) -> list[str]:
    """``region`` cut at the commas separating arguments, nesting left alone."""
    depth, cuts = 0, []
    for index, character in _scan(region):
        if character in _OPENING:
            depth += 1
        elif character in _CLOSING:
            depth -= 1
        elif character == "," and depth == 0:
            cuts.append(index)
    bounds = [-1, *cuts, len(region)]
    return [region[start + 1:end] for start, end in zip(bounds, bounds[1:])]


def _keyword(argument: str) -> str | None:
    """The parameter an argument names, when it supplies one by keyword."""
    match = _KEYWORD.match(argument)
    return match[1] if match else None


def _scan(text: str) -> Iterator[tuple[int, str]]:
    """Every ``(offset, character)`` of ``text`` outside a string or a comment."""
    index = 0
    while index < len(text):
        character = text[index]
        if character in "\"'":
            index = _skip_string(text, index)
        elif character == "#":
            index = text.find("\n", index)
            if index < 0:
                return
        else:
            yield index, character
            index += 1


def _skip_string(text: str, start: int) -> int:
    """The offset just past the string literal opening at ``start``."""
    quote = text[start] * 3 if text[start:start + 3] == text[start] * 3 else text[start]
    index = start + len(quote)
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text.startswith(quote, index):
            return index + len(quote)
        else:
            index += 1
    return len(text)
