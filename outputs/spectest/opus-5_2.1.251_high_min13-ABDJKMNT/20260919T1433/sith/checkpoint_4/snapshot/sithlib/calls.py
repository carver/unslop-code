"""Locating the call a cursor is writing arguments for.

A call being typed is usually not valid Python yet - its closing parenthesis
has not been written - so the call is read from the source text before the
cursor rather than from the parsed tree. Strings, comments and nested
brackets are stepped over, leaving the innermost parenthesis still open.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .context import CLOSERS, IDENTIFIER_CHARS, QUOTES, expression_start
from .source import Source

OPENERS = "([{"
DEFINING = {"def", "class"}
KEYWORD_ARGUMENT = re.compile(r"\s*(?P<name>[A-Za-z_]\w*)\s*=(?!=)")
UNPACKED_KEYWORDS = "**"


@dataclass
class CallSite:
    """The call a cursor sits inside, as far as it has been written."""

    callee: str
    """Source text of the expression being called."""
    keyword: Optional[str]
    """Name of the keyword argument under the cursor, when it writes one."""
    rank: int
    """How many positional arguments are written before the cursor's."""


def call_at(source: Source, line: int, col: int) -> Optional[CallSite]:
    """The call whose argument list holds the cursor, if any."""
    text = _text_before(source, line, col)
    opened = _open_group(text)
    if opened is None or text[opened] != "(":
        return None
    callee = _callee(text[:opened])
    if callee is None:
        return None
    return CallSite(callee, *_written(text[opened + 1:]))


def _text_before(source: Source, line: int, col: int) -> str:
    """The file up to the cursor, with the cursor position checked."""
    current = source.line_at(line, col)
    return "\n".join(source.lines[:line - 1] + [current[:col]])


def _open_group(text: str) -> Optional[int]:
    """Index of the innermost bracket left open before the cursor."""
    stack: List[int] = []
    index = 0
    while index < len(text):
        skipped = _skipped(text, index)
        if skipped is not None:
            index = skipped
            continue
        if text[index] in OPENERS:
            stack.append(index)
        elif text[index] in CLOSERS and stack:
            stack.pop()
        index += 1
    return stack[-1] if stack else None


def _skipped(text: str, index: int) -> Optional[int]:
    """Index just past a string literal or comment beginning at ``index``."""
    if text[index] == "#":
        ended = text.find("\n", index)
        return len(text) if ended < 0 else ended
    if text[index] not in QUOTES:
        return None
    quote = text[index] * 3 if text.startswith(text[index] * 3, index) else text[index]
    return _string_end(text, index + len(quote), quote)


def _string_end(text: str, start: int, quote: str) -> int:
    """Index just past the end of a string literal already opened."""
    index = start
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text.startswith(quote, index):
            return index + len(quote)
        index += 1
    return len(text)


def _callee(head: str) -> Optional[str]:
    """The expression written immediately before the open parenthesis.

    A parenthesis that follows nothing groups an expression, and one that
    follows a keyword belongs to a statement; neither is a call.
    """
    written = head.rstrip()
    start = expression_start(written, len(written))
    called = written[start:]
    if not called or keyword.iskeyword(called.rpartition(".")[2]):
        return None
    return None if _word_before(written[:start]) in DEFINING else called


def _word_before(text: str) -> str:
    """The identifier a piece of source ends with, ignoring trailing space."""
    stripped = text.rstrip()
    index = len(stripped)
    while index and stripped[index - 1] in IDENTIFIER_CHARS:
        index -= 1
    return stripped[index:]


def _written(text: str) -> Tuple[Optional[str], int]:
    """The keyword the cursor is writing and the positional arguments before it."""
    arguments = _split(text)
    preceding = [argument for argument in arguments[:-1] if _binds_positionally(argument)]
    return _keyword_of(arguments[-1]), len(preceding)


def _binds_positionally(argument: str) -> bool:
    """Whether a written argument takes up a positional slot of the call."""
    return _keyword_of(argument) is None and not argument.strip().startswith(UNPACKED_KEYWORDS)


def _keyword_of(argument: str) -> Optional[str]:
    """The parameter a written argument names, when it names one."""
    written = KEYWORD_ARGUMENT.match(argument)
    return written.group("name") if written is not None else None


def _split(text: str) -> List[str]:
    """The arguments written so far, divided at the commas of this call."""
    arguments: List[str] = []
    depth = start = index = 0
    while index < len(text):
        skipped = _skipped(text, index)
        if skipped is not None:
            index = skipped
            continue
        if text[index] in OPENERS:
            depth += 1
        elif text[index] in CLOSERS:
            depth -= 1
        elif text[index] == "," and depth == 0:
            arguments.append(text[start:index])
            start = index + 1
        index += 1
    return arguments + [text[start:]]
