"""What the cursor is asking for: a name, an attribute, or part of an import."""

from __future__ import annotations

import ast
import re
import string
from dataclasses import dataclass
from typing import Optional, Tuple

from .source import indent_of

NAME = "name"
ATTRIBUTE = "attribute"
MODULE_PATH = "module-path"
IMPORT_NAME = "import-name"

IDENTIFIER_CHARS = set(string.ascii_letters + string.digits + "_")
CLOSERS = {")": "(", "]": "[", "}": "{"}
QUOTES = "\"'"

MODULE_PATHS = re.compile(r"\s*(?:import|from)\s+(?:[\w.]+\s*,\s*)*(?P<path>[\w.]*)$")
IMPORT_NAMES = re.compile(
    r"\s*from\s+(?P<module>[\w.]+)\s+import\s+\(?\s*(?:[\w.]+(?:\s+as\s+\w+)?\s*,\s*)*$"
)


@dataclass
class Context:
    """The completion request described by a cursor position."""

    kind: str
    prefix: str
    receiver: str = ""
    """Source text of the expression before the dot, for attribute contexts."""
    module: str = ""
    """Module path written in the import statement, for import contexts."""
    indent: int = 0
    """Indentation the cursor sits at, used to place it in a scope."""


def context_at(text: str, col: int) -> Context:
    """Read the completion context out of a line of source and a column."""
    start = col
    while start > 0 and text[start - 1] in IDENTIFIER_CHARS:
        start -= 1
    prefix = text[start:col]
    indent = cursor_indent(text, col)
    written = import_context(text[:start])
    if written is not None:
        kind, module = written
        return Context(kind, prefix, module=module, indent=indent)
    if start > 0 and text[start - 1] == ".":
        dot = start - 1
        return Context(ATTRIBUTE, prefix, text[expression_start(text, dot):dot], indent)
    return Context(NAME, prefix, indent=indent)


def import_context(head: str) -> Optional[Tuple[str, str]]:
    """The import completion the text before the cursor asks for, if any.

    A cursor inside an import statement is either naming a module - after
    `import`, after `from`, or after a dot in either - or naming something to
    take out of the module a `from` clause already named.
    """
    names = IMPORT_NAMES.fullmatch(head)
    if names is not None:
        return IMPORT_NAME, names.group("module")
    path = MODULE_PATHS.fullmatch(head)
    return (MODULE_PATH, path.group("path")) if path is not None else None


def parse_expression(text: str) -> Optional[ast.expr]:
    """Parse a written expression, such as the receiver before a dot."""
    try:
        return ast.parse(text.strip(), mode="eval").body
    except SyntaxError:
        return None


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
