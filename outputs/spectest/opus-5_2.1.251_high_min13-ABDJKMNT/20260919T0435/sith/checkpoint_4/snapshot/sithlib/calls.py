"""Finding the call the cursor is typing arguments for.

A call being written is routinely unparsable -- its closing parenthesis has not
been typed yet -- so the text before the cursor is tokenized rather than
parsed, and the innermost bracket still open at the cursor is the call.
"""

from __future__ import annotations

import keyword
import tokenize
from dataclasses import dataclass

from .params import Argument

OPENERS = "([{"
CLOSERS = ")]}"


@dataclass(frozen=True)
class CallSite:
    """The expression being called, and the argument the cursor sits in."""

    callee: str
    argument: Argument


def call_at(lines: list[str], line: int, col: int) -> CallSite | None:
    """The call whose argument list holds the cursor, or None if it is elsewhere."""
    text = lines[: line - 1] + [lines[line - 1][:col]]
    tokens = _tokens(text)
    for frame in reversed(_open_frames(tokens)):
        callee = _callee(text, tokens, frame.opener) if frame.bracket == "(" else None
        if callee:
            return CallSite(callee, Argument(frame.position, frame.keyword))
    return None


@dataclass
class _Frame:
    """A bracket that is still open at the cursor."""

    bracket: str
    opener: int  # index of the opening token
    position: int = 0
    keyword: str | None = None


def _open_frames(tokens: list[tokenize.TokenInfo]) -> list[_Frame]:
    """The brackets still open at the end of the text, outermost first."""
    stack: list[_Frame] = []
    for index, token in enumerate(tokens):
        if token.type != tokenize.OP:
            continue
        if token.string in OPENERS:
            stack.append(_Frame(token.string, index))
        elif token.string in CLOSERS and stack:
            stack.pop()
        elif not stack:
            continue
        elif token.string == ",":
            stack[-1].position += 1
            stack[-1].keyword = None
        elif token.string == "=":
            stack[-1].keyword = _keyword_before(tokens, index)
    return stack


def _keyword_before(tokens: list[tokenize.TokenInfo], index: int) -> str | None:
    """The name of a `name=` argument, when the `=` really starts one."""
    if index < 2 or tokens[index - 1].type != tokenize.NAME:
        return None
    opening = tokens[index - 2]
    starts = opening.type == tokenize.OP and opening.string in f"{OPENERS},"
    return tokens[index - 1].string if starts else None


def _callee(lines: list[str], tokens: list[tokenize.TokenInfo], opener: int) -> str | None:
    """The source of the expression called at the bracket token `opener`."""
    start = _callee_start(tokens, opener)
    return None if start is None else _slice(lines, tokens[start].start, tokens[opener].start)


def _callee_start(tokens: list[tokenize.TokenInfo], opener: int) -> int | None:
    """Index of the first token of a dotted chain of atoms ending at `opener`."""
    start = _atom_start(tokens, opener - 1)
    while start is not None and start > 0 and _is_dot(tokens[start - 1]):
        earlier = _atom_start(tokens, start - 2)
        if earlier is None:
            break
        start = earlier
    return start


def _atom_start(tokens: list[tokenize.TokenInfo], end: int) -> int | None:
    """Index of the first token of the single atom ending at token `end`."""
    if end < 0:
        return None
    token = tokens[end]
    if token.type == tokenize.OP and token.string in CLOSERS:
        opener = _matching_opener(tokens, end)
        if opener is None:
            return None
        called = _atom_start(tokens, opener - 1)
        return opener if called is None else called
    if token.type == tokenize.STRING:
        return end
    named = token.type == tokenize.NAME and not keyword.iskeyword(token.string)
    return end if named else None


def _matching_opener(tokens: list[tokenize.TokenInfo], end: int) -> int | None:
    depth = 0
    for index in range(end, -1, -1):
        token = tokens[index]
        if token.type != tokenize.OP:
            continue
        if token.string in CLOSERS:
            depth += 1
        elif token.string in OPENERS:
            depth -= 1
            if depth == 0:
                return index
    return None


def _is_dot(token: tokenize.TokenInfo) -> bool:
    return token.type == tokenize.OP and token.string == "."


def _slice(lines: list[str], start: tuple[int, int], end: tuple[int, int]) -> str:
    """The text between two `(row, column)` token positions."""
    if start[0] == end[0]:
        return lines[start[0] - 1][start[1] : end[1]]
    spanned = [lines[start[0] - 1][start[1] :], *lines[start[0] : end[0] - 1]]
    return "\n".join([*spanned, lines[end[0] - 1][: end[1]]])


def _tokens(lines: list[str]) -> list[tokenize.TokenInfo]:
    """The tokens of the text, up to the point where it stops tokenizing.

    Text cut off at the cursor ends inside an open bracket by definition, which
    the tokenizer reports as an error only once it has yielded everything else.
    """
    reader = iter([f"{line}\n" for line in lines]).__next__
    found: list[tokenize.TokenInfo] = []
    try:
        found.extend(tokenize.generate_tokens(reader))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return found
