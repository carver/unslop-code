"""The `extract-variable` and `extract-function` commands.

Both lift a piece of a file out and give it a name: an expression becomes an
assignment just above the statement it was written in, and a run of statements
becomes a function beside the one they were written in.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from . import project, scopes, spans
from .edits import Buffer, Workspace
from .refactor import identifier
from .source import SithError
from .spans import Position

INDENT = "    "
NOT_AN_EXPRESSION = "selection is not a complete expression"
NOT_A_STATEMENT = "selection is not a complete statement"

#: The binding forms that make a name a variable rather than a definition or
#: an import, which is what a name read by extracted code may be.
VARIABLES = (scopes.ASSIGN, scopes.TARGET, scopes.PARAM, scopes.EXCEPT)


def extract_variable(path: str, line: int, col: int, until: Position, name: str,
                     root: str | None = None, diff: bool = False) -> dict | str:
    """Name the selected expression, and use that name where it stood."""
    identifier(name)
    workspace = Workspace(project.root_of(path, root))
    buffer = workspace.buffer_for(path)
    tree = spans.parse(buffer.original, buffer.path)
    expression = spans.expression_spanning(tree, (line, col), until)
    if expression is None:
        raise SithError(NOT_AN_EXPRESSION)
    statement = spans.statement_containing(tree, spans.span(expression)[0])
    buffer.replace(*spans.span(expression), name)
    source = ast.get_source_segment(buffer.original, expression)
    indent = _indent(buffer.lines[statement.lineno - 1])
    buffer.insert_lines(statement.lineno, [f"{indent}{name} = {source}"])
    return workspace.answer(diff)


def extract_function(path: str, line: int, col: int, until: Position, name: str,
                     root: str | None = None, diff: bool = False) -> dict | str:
    """Move the selected statements into a new function, and call it where they stood."""
    identifier(name)
    workspace = Workspace(project.root_of(path, root))
    buffer = workspace.buffer_for(path)
    tree = spans.parse(buffer.original, buffer.path)
    selection = Selection.of(tree, buffer, line, until[0])
    parameters = selection.parameters()
    results = selection.results(tree)
    buffer.replace_lines(selection.first, selection.last,
                         [selection.call(name, parameters, results)])
    anchor, indent = _placement(tree, buffer, selection.first)
    body = selection.body(indent)
    buffer.insert_lines(anchor, _function(name, parameters, results, body, indent))
    return workspace.answer(diff)


@dataclass(frozen=True)
class Selection:
    """The statements `extract-function` is lifting out of a file."""

    statements: list[ast.stmt]
    buffer: Buffer
    #: The names bound outside the selection that the extracted code may read.
    outer: set[str]

    @classmethod
    def of(cls, tree: ast.Module, buffer: Buffer, first: int, last: int) -> "Selection":
        first, last = _trimmed(buffer, first, last)
        statements = spans.statements_between(tree, first, last)
        if not statements:
            raise SithError(NOT_A_STATEMENT)
        return cls(statements, buffer, _outer_names(tree, buffer, first, last))

    @property
    def first(self) -> int:
        return self.statements[0].lineno

    @property
    def last(self) -> int:
        return self.statements[-1].end_lineno

    @property
    def indent(self) -> str:
        return _indent(self.buffer.lines[self.first - 1])

    def parameters(self) -> list[str]:
        """The names the selection reads before binding them, first use first."""
        bound: set[str] = set()
        found: list[str] = []
        for statement in self.statements:
            for name in _reads(statement):
                if name in self.outer and name not in bound and name not in found:
                    found.append(name)
            bound.update(_writes(statement))
        return found

    def results(self, tree: ast.Module) -> list[str]:
        """The names the selection binds that the code below it goes on to read."""
        later = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            and node.lineno > self.last
        }
        written = dict.fromkeys(name for statement in self.statements
                                for name in _writes(statement))
        return [name for name in written if name in later]

    def body(self, indent: str) -> list[str]:
        """The selected lines, moved from their own indentation into the function."""
        prefix = indent + INDENT
        lines = self.buffer.lines[self.first - 1: self.last]
        return [prefix + line[len(self.indent):] if line.strip() else line for line in lines]

    def call(self, name: str, parameters: list[str], results: list[str]) -> str:
        """The line that replaces the selection: a call, holding onto its results."""
        call = f"{name}({', '.join(parameters)})"
        targets = ", ".join(results)
        return f"{self.indent}{targets} = {call}" if results else f"{self.indent}{call}"


def _function(name: str, parameters: list[str], results: list[str], body: list[str],
              indent: str) -> list[str]:
    """The extracted function, followed by a blank line to stand apart."""
    answer = [f"{indent}{INDENT}return {', '.join(results)}"] if results else []
    return [f"{indent}def {name}({', '.join(parameters)}):", *body, *answer, ""]


def _placement(tree: ast.Module, buffer: Buffer, first: int) -> tuple[int, str]:
    """The line the extracted function goes above, and the indentation it takes.

    A function extracted out of another one is written beside it rather than
    inside it; one extracted at module level simply takes the place of the
    statements it holds.
    """
    holder = spans.enclosing_definition(tree, first)
    if holder is None:
        return first, _indent(buffer.lines[first - 1])
    header = spans.header_line(holder)
    return header, _indent(buffer.lines[header - 1])


def _outer_names(tree: ast.Module, buffer: Buffer, first: int, last: int) -> set[str]:
    """The variables bound outside the selection that code inside it can see."""
    built = scopes.build(tree)
    scope = scopes.scope_at(built, first, len(_indent(buffer.lines[first - 1])))
    return {
        binding.name
        for holder in scopes.lookup_chain(scope)
        for binding in holder.bindings
        if binding.form in VARIABLES and not first <= binding.lineno <= last
    }


def _trimmed(buffer: Buffer, first: int, last: int) -> tuple[int, int]:
    """The selected lines, narrowed past the blank lines and comments at each end."""
    while first < last and _is_filler(buffer.lines[first - 1]):
        first += 1
    while last > first and _is_filler(buffer.lines[last - 1]):
        last -= 1
    return first, last


def _is_filler(line: str) -> bool:
    """Whether a line carries no statement of its own."""
    return not line.strip() or line.lstrip().startswith("#")


def _reads(statement: ast.stmt) -> list[str]:
    """The names a statement reads, in the order they are written.

    Everything a statement reads is answered before anything it binds, which
    is the order a statement runs in: `total = total + 1` reads the total it
    goes on to replace.  An augmented assignment reads the target it writes.
    """
    names = [name.id for name in _in_order(statement) if isinstance(name.ctx, ast.Load)]
    if isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
        return [statement.target.id] + names
    return names


def _writes(statement: ast.stmt) -> list[str]:
    """The names a statement binds, in the order they are written."""
    return [name.id for name in _in_order(statement) if isinstance(name.ctx, ast.Store)]


def _in_order(statement: ast.stmt) -> list[ast.Name]:
    found = [node for node in ast.walk(statement) if isinstance(node, ast.Name)]
    return sorted(found, key=lambda node: (node.lineno, node.col_offset))


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]
