"""Reading a source file and describing what sits at the cursor."""

import ast
import os
import re
from dataclasses import dataclass

from .bindings import identifier_column
from .errors import SithError

_IDENTIFIER_TAIL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


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
    text = line_at(lines, line, column)
    head = text[:column]
    match = _IDENTIFIER_TAIL.search(head)
    prefix = match.group() if match else ""
    before = head[: len(head) - len(prefix)].rstrip()
    receiver = _parse_receiver(before[:-1]) if before.endswith(".") else None
    indent = column if not text.strip() else len(text) - len(text.lstrip())
    return Cursor(line=line, prefix=prefix, indent=indent, receiver=receiver)


def line_at(lines, line, column):
    """The text of a cursor line, rejecting positions outside the file."""
    if not 1 <= line <= len(lines):
        raise SithError(f"line {line} is out of range (file has {len(lines)} lines)")
    text = lines[line - 1]
    if not 0 <= column <= len(text):
        raise SithError(f"column {column} is out of range (line has {len(text)} characters)")
    return text


def identifier_at(module, line, column):
    """The node the cursor sits on: a name, a definition or a literal.

    Cursors on anything else - an operator, a keyword, a comment - have
    nothing to resolve and are reported as an error.
    """
    text = line_at(module.lines, line, column)
    found = _named_node(module, line, _word_at(text, column))
    if found is None:
        found = _literal_at(module.tree, line, column)
    if found is None:
        raise SithError(f"no name at line {line}, column {column}")
    return found


def _word_at(text, column):
    """The identifier the cursor sits on or just after, as a match."""
    return next(
        (match for match in _IDENTIFIER.finditer(text)
         if match.start() <= column <= match.end()),
        None,
    )


def _named_node(module, line, word):
    if word is None:
        return None
    wanted = (word.group(), line, word.start())
    return next(
        (node for node in ast.walk(module.tree)
         if _identifier(node, module.lines) == wanted),
        None,
    )


def _literal_at(tree, line, column):
    """The literal the cursor sits inside, for values that have no name."""
    return next(
        (node for node in ast.walk(tree)
         if isinstance(node, ast.Constant)
         and node.lineno == line
         and node.col_offset <= column <= node.end_col_offset),
        None,
    )


def _identifier(node, lines):
    """The name a node declares or uses, and where that identifier starts."""
    if isinstance(node, ast.Name):
        return node.id, node.lineno, node.col_offset
    if isinstance(node, ast.Attribute):
        return node.attr, node.end_lineno, node.end_col_offset - len(node.attr)
    if isinstance(node, ast.arg):
        return node.arg, node.lineno, node.col_offset
    if isinstance(node, _DEFINITIONS):
        return node.name, node.lineno, identifier_column(lines, node.lineno, node.name,
                                                         node.col_offset)
    if isinstance(node, ast.alias):
        bound = node.asname or node.name.split(".")[0]
        return bound, node.lineno, identifier_column(lines, node.lineno, bound, node.col_offset)
    return None


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
