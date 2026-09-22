"""Deciding what the cursor is in the middle of typing."""

from __future__ import annotations

from dataclasses import dataclass

CLOSERS = {")": "(", "]": "[", "}": "{"}
OPENERS = {opener: closer for closer, opener in CLOSERS.items()}
SPACE = " \t"


@dataclass(frozen=True)
class CursorContext:
    """The partially typed prefix and, after a `.`, the receiver before it."""

    line: int
    col: int
    prefix: str
    receiver: str | None

    @property
    def is_attribute(self) -> bool:
        return self.receiver is not None


def analyze(line_text: str, line: int, col: int) -> CursorContext:
    """Split the text left of the cursor into a receiver and a typed prefix."""
    before = line_text[:col]
    prefix = before[_identifier_start(before, len(before)) :]
    head = before[: len(before) - len(prefix)].rstrip(SPACE)
    if not head.endswith("."):
        return CursorContext(line, col, prefix, None)
    return CursorContext(line, col, prefix, _atom_before(head[:-1]))


def _is_identifier_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _identifier_start(text: str, end: int) -> int:
    while end > 0 and _is_identifier_char(text[end - 1]):
        end -= 1
    return end


def _atom_before(text: str) -> str | None:
    """The source of the expression ending at `text`, e.g. `a.b(c).d` or `'x'`."""
    end = len(text.rstrip(SPACE))
    stop = end
    while True:
        start = _atom_start(text, stop)
        if start is None:
            break
        stop = start
        dot = len(text[:stop].rstrip(SPACE)) - 1
        if dot < 0 or text[dot] != ".":
            break
        stop = dot
    return text[stop:end].strip() or None


def _atom_start(text: str, end: int) -> int | None:
    """Start index of the single atom ending at `end`, or None if there isn't one."""
    end = len(text[:end].rstrip(SPACE))
    if end == 0:
        return None
    char = text[end - 1]
    if char in CLOSERS:
        opener = _matching_opener(text, end)
        if opener is None:
            return None
        # A bracket may be a call or subscript hanging off a preceding atom.
        callee = _atom_start(text, opener)
        return opener if callee is None else callee
    if char in "\"'":
        return _string_start(text, end)
    if _is_identifier_char(char):
        return _identifier_start(text, end)
    return None


def _matching_opener(text: str, end: int) -> int | None:
    depth = 0
    for index in range(end - 1, -1, -1):
        char = text[index]
        if char in CLOSERS:
            depth += 1
        elif char in OPENERS:
            depth -= 1
            if depth == 0:
                return index
    return None


def _string_start(text: str, end: int) -> int | None:
    quote = text[end - 1]
    index = text.rfind(quote, 0, end - 1)
    return index if index >= 0 else None
