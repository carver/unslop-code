"""Reading a source file and describing what sits at the cursor."""

import ast
import os
import re
from dataclasses import dataclass

from .bindings import alias_column, identifier_column
from .errors import SithError

_IDENTIFIER_TAIL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

_IMPORTED_NAME = re.compile(
    r"^\s*from\s+(\.*)([\w.]*)\s+import\s+\(?\s*(?:[\w.]+(?:\s+as\s+\w+)?\s*,\s*)*$"
)
_IMPORTED_MODULE = re.compile(
    r"^\s*(?:import|from)\s+(?:[\w.]+\s*,\s*)*(\.*)((?:\w+\.)*)$"
)


@dataclass(frozen=True)
class ImportTarget:
    """The module a half-typed import statement names.

    `members` is True past the ``import`` keyword, where the names inside the
    module are wanted, and False while the module itself is still being typed.
    `level` counts the leading dots of a relative import.
    """

    dotted: str
    level: int
    members: bool


@dataclass(frozen=True)
class Cursor:
    """Where the cursor is and what the surrounding text asks for.

    `receiver` is the expression left of a trailing dot for attribute
    completion, and ``None`` when a bare name is being typed. `imports` is set
    instead when the cursor sits inside an import statement.
    """

    line: int
    prefix: str
    indent: int
    receiver: ast.expr = None
    imports: ImportTarget = None


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
    typed = head[: len(head) - len(prefix)]
    imports = _import_target(typed)
    before = typed.rstrip()
    receiver = (trailing_expression(before[:-1])
                if imports is None and before.endswith(".") else None)
    indent = column if not text.strip() else len(text) - len(text.lstrip())
    return Cursor(line=line, prefix=prefix, indent=indent, receiver=receiver, imports=imports)


def _import_target(typed):
    """The import statement the text left of the cursor opens, if it opens one."""
    named = _IMPORTED_NAME.match(typed)
    if named is not None:
        return ImportTarget(named.group(2), len(named.group(1)), members=True)
    module = _IMPORTED_MODULE.match(typed)
    if module is None:
        return None
    return ImportTarget(module.group(2).rstrip("."), len(module.group(1)), members=False)


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
         if identifier_of(node, module.lines) == wanted),
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


def name_at(module, line, column):
    """The node the cursor names, the name it spells and the line it sits on.

    A cursor on something that has no name of its own - a literal, a comment -
    has nothing to rename or resolve and is reported as an error.
    """
    node = identifier_at(module, line, column)
    found = identifier_of(node, module.lines)
    if found is None:
        raise SithError(f"no name at line {line}, column {column}")
    return node, found[0], found[1]


def identifier_of(node, lines):
    """The name a node declares or uses, and where that identifier starts.

    Nodes that neither declare nor use a name - a call, an operator, a body -
    have no identifier and are reported as ``None``.
    """
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
        return bound, node.lineno, alias_column(lines, node)
    return None


def parse_expression(text):
    """The expression `text` spells, or ``None`` when it spells none."""
    try:
        return ast.parse(text.strip(), mode="eval").body
    except SyntaxError:
        return None


def trailing_expression(text):
    """The longest trailing slice of `text` that is a valid expression.

    The text left of a dot or an open bracket is usually a fragment such as
    ``print(value`` or ``x = obj.field``; walking the start forward finds the
    expression it ends with. A slice may only start where an identifier does
    not, so that the ``f`` of ``if`` is never read as a name.
    """
    for start in range(len(text)):
        if start and (text[start - 1].isalnum() or text[start - 1] == "_"):
            continue
        found = parse_expression(text[start:])
        if found is not None:
            return found
    return None


def span_text(lines, line, column, until_line, until_column):
    """The source text between two positions, over one line or several."""
    if line == until_line:
        return lines[line - 1][column:until_column]
    head = lines[line - 1][column:]
    tail = lines[until_line - 1][:until_column]
    return "\n".join([head] + lines[line:until_line - 1] + [tail])
