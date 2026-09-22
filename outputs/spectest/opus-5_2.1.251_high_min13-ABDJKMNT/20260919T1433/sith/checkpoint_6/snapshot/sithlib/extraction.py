"""The `extract-variable` and `extract-function` subcommands.

Both commands name a piece of code and put the name where the code was:
an expression becomes a variable assigned just above its statement, and a run
of statements becomes a function defined just above the one holding them.
"""

from __future__ import annotations

import ast
from typing import List, Sequence, Tuple

from .analysis import Analyzer, Scope, lookup_chain
from .dataflow import Flow, names_read_after
from .edits import (
    Edit,
    Refactoring,
    checked_identifier,
    indentation,
    insertion,
    line_span,
    source_text,
)
from .project import Project
from .selections import (
    Selection,
    enclosing_definition,
    first_line,
    selected_expression,
    selected_statements,
    statement_around,
)
from .source import Source

INDENT = " " * 4
IMPORTED_OR_DEFINED = (
    ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom
)
"""Bindings the extracted function reaches without being handed them."""

AWAITING = (ast.Await, ast.AsyncFor, ast.AsyncWith)


def extract_variable(
    source: Source, project: Project, line: int, col: int,
    until: Tuple[int, int], name: str, diff: bool,
) -> str:
    """Name the selected expression and use the name where it stood."""
    checked_identifier(name)
    selection = Selection.between(line, col, until, source.lines)
    expression = selected_expression(source.tree, selection, source.lines)
    statement = statement_around(source.tree, expression)
    assigned = source_text(source.lines, expression)
    edits = [
        insertion(
            source.path, statement.lineno,
            f"{indentation(source.lines, statement.lineno)}{name} = {assigned}\n",
        ),
        Edit(
            source.path, selection.line, selection.column,
            selection.until_line, selection.until_column, name,
        ),
    ]
    return Refactoring(project.root, edits).report(diff)


def extract_function(
    source: Source, project: Project, line: int, col: int,
    until: Tuple[int, int], name: str, diff: bool,
) -> str:
    """Move the selected statements into a function and call it where they were."""
    checked_identifier(name)
    selection = Selection.between(line, col, until, source.lines)
    statements = selected_statements(source.tree, selection)
    analyzer = project.analyzer_for(source)
    scope = analyzer.scope_at(selection.line, statements[0].col_offset)
    flow = Flow(statements)
    parameters = [
        read for read in flow.reads if _is_outer_variable(analyzer, scope, read, selection)
    ]
    returns = _returns(scope, flow, selection)
    waits = _waits(statements)
    edits = [
        insertion(
            source.path,
            *_definition(source, statements, selection, name, parameters, returns, waits),
        ),
        line_span(
            source.path, statements[0].lineno, statements[-1].end_lineno,
            _call(source, statements, name, parameters, returns, waits),
        ),
    ]
    return Refactoring(project.root, edits).report(diff)


def _definition(
    source: Source, statements: List[ast.stmt], selection: Selection,
    name: str, parameters: List[str], returns: List[str], waits: bool,
) -> Tuple[int, str]:
    """Where the new function goes and how it is written there.

    It goes above the definition the statements were taken out of, at that
    definition's own indentation; statements taken from module level keep
    their place, with the function written immediately above them.
    """
    holder = enclosing_definition(source.tree, selection)
    at = first_line(holder) if holder is not None else statements[0].lineno
    indent = indentation(source.lines, at)
    header = f"{'async ' if waits else ''}def {name}({', '.join(parameters)}):"
    body = _reindented(source.lines, statements, indent + INDENT)
    tail = [f"{indent}{INDENT}return {', '.join(returns)}"] if returns else []
    return at, "\n".join([indent + header, *body, *tail, "", ""])


def _call(
    source: Source, statements: List[ast.stmt], name: str,
    parameters: List[str], returns: List[str], waits: bool,
) -> str:
    """The line that calls the extracted function where its code used to be."""
    call = f"{'await ' if waits else ''}{name}({', '.join(parameters)})"
    taken = f"{', '.join(returns)} = {call}" if returns else call
    return f"{indentation(source.lines, statements[0].lineno)}{taken}\n"


def _reindented(lines: Sequence[str], statements: List[ast.stmt], indent: str) -> List[str]:
    """The selected lines, moved to the indentation of the new function's body."""
    block = lines[statements[0].lineno - 1:statements[-1].end_lineno]
    removed = len(indentation(lines, statements[0].lineno))
    return [indent + line[removed:] if line.strip() else "" for line in block]


def _waits(statements: List[ast.stmt]) -> bool:
    """Whether the block waits on something, which its function must do too."""
    return any(
        isinstance(node, AWAITING) for statement in statements for node in ast.walk(statement)
    )


def _returns(scope: Scope, flow: Flow, selection: Selection) -> List[str]:
    """The names the block sets that the code after it still reads."""
    later = names_read_after(scope.node, selection.until_line)
    return [written for written in flow.writes if written in later]


def _is_outer_variable(
    analyzer: Analyzer, scope: Scope, name: str, selection: Selection
) -> bool:
    """Whether a name the block reads is a variable it is handed from outside.

    Functions, classes and imports stay where they are: the extracted function
    reaches them as it stands, and passing them in would only obscure them.
    """
    for current in lookup_chain(scope):
        for symbol in analyzer.bindings(current):
            if symbol.name == name and not selection.covers(symbol.lineno):
                return symbol.node is not None and not isinstance(symbol.node, IMPORTED_OR_DEFINED)
    return False
