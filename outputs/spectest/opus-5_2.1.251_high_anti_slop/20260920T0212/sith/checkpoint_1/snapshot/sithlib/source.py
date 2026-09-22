"""Reading a source file and describing what sits at the cursor."""

import ast
import os
import re
from dataclasses import dataclass

from .errors import SithError

_IDENTIFIER_TAIL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Cursor:
    """Where the cursor is and what the surrounding text asks for.

    `receiver` is the expression left of a trailing dot for attribute
    completion, and ``None`` when a bare name is being typed.
    """

    line: int
    prefix: str
    indent: int
    receiver: ast.expr = None


def read_source(path):
    """Return the decoded contents of `path`."""
    if not os.path.isfile(path):
        raise SithError(f"not a regular file: {path}")
    with open(path, "rb") as handle:
        data = handle.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise SithError(f"file is not valid UTF-8: {path}") from None


def locate(lines, line, column):
    """Build the `Cursor` for a 1-based line and 0-based column."""
    if not 1 <= line <= len(lines):
        raise SithError(f"line {line} is out of range (file has {len(lines)} lines)")
    text = lines[line - 1]
    if not 0 <= column <= len(text):
        raise SithError(f"column {column} is out of range (line has {len(text)} characters)")

    head = text[:column]
    match = _IDENTIFIER_TAIL.search(head)
    prefix = match.group() if match else ""
    before = head[: len(head) - len(prefix)].rstrip()
    receiver = _parse_receiver(before[:-1]) if before.endswith(".") else None
    indent = column if not text.strip() else len(text) - len(text.lstrip())
    return Cursor(line=line, prefix=prefix, indent=indent, receiver=receiver)


def _parse_receiver(text):
    """Parse the longest trailing slice of `text` that is a valid expression.

    The text left of a dot is usually a fragment such as ``print(value`` or
    ``x = obj``; walking the start forward finds the receiver ``value``/``obj``.
    """
    for start in range(len(text)):
        try:
            return ast.parse(text[start:].strip(), mode="eval").body
        except SyntaxError:
            continue
    return None
