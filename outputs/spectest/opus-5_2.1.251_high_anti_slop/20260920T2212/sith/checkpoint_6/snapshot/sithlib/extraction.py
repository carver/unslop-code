"""Pulling a selection out into a name of its own.

Extracting a variable is a matter of text: the expression moves to an
assignment above the statement it was written in.  Extracting a function also
has to work out what crosses the new boundary -- the names the selection reads
from outside become its parameters, and the names it writes that are read
afterwards become what it returns.
"""

from __future__ import annotations

import ast
import textwrap
from typing import Iterator

from .cursor import all_names, defines
from .edits import Edit, Refactoring, collect
from .errors import SithError
from .project import Analysis
from .references import resolve
from .scopes import Scope
from .source import SourceFile
from .trees import (Span, definition_holding, expression_spanning, first_line,
                    statement_holding, statements_spanning)


def extract_variable(analysis: Analysis, source: SourceFile, span: Span,
                     name: str) -> Refactoring:
    """Name the selected expression, above the statement it is written in."""
    expression = expression_spanning(analysis.tree, span)
    if expression is None:
        raise SithError("selection is not a complete expression")
    statement = statement_holding(analysis.tree, expression)
    indent = _indentation(source.lines[statement.lineno - 1])
    path = analysis.info.path
    return collect([Edit(path, Span(statement.lineno, 0, statement.lineno, 0),
                         f"{indent}{name} = {source.segment(span)}\n"),
                    Edit(path, span, name)],
                   {path: source.text})


def extract_function(analysis: Analysis, source: SourceFile, span: Span,
                     name: str) -> Refactoring:
    """Move the selected statements into a function, called where they stood."""
    statements = statements_spanning(analysis.tree, span)
    if statements is None:
        raise SithError("selection is not a complete run of statements")
    scope = analysis.module.scope.innermost(span.line)
    parameters = _parameters(statements, scope, span)
    results = _results(analysis, statements, span)
    owner = definition_holding(analysis.tree, statements[0])
    anchor = span.line if owner is None else first_line(owner)
    indent = "" if owner is None else _indentation(source.lines[anchor - 1])
    call = _call(_indentation(source.lines[span.line - 1]), name, parameters, results)
    path = analysis.info.path
    return collect([Edit(path, Span(anchor, 0, anchor, 0),
                         _function(name, parameters, results, indent,
                                   source.block(span.line, span.end_line))),
                    Edit(path, source.whole_lines(span.line, span.end_line), call)],
                   {path: source.text})


def _function(name: str, parameters: list[str], results: list[str], indent: str,
              body: str) -> str:
    """The extracted function, written to sit at ``indent``.

    A function of its own at module level is separated by two blank lines and a
    nested one by a single blank line, as the style the rest of a file follows.
    """
    inner = f"{indent}    "
    written = [f"{indent}def {name}({', '.join(parameters)}):\n",
               textwrap.indent(textwrap.dedent(body), inner)]
    if results:
        written.append(f"{inner}return {', '.join(results)}\n")
    written.append("\n" if indent else "\n\n")
    return "".join(written)


def _call(indent: str, name: str, parameters: list[str], results: list[str]) -> str:
    """The call that stands where the selected statements stood."""
    bound = f"{', '.join(results)} = " if results else ""
    return f"{indent}{bound}{name}({', '.join(parameters)})\n"


def _parameters(statements: list[ast.stmt], scope: Scope, span: Span) -> list[str]:
    """The names the selection reads but does not itself set, in order of first use.

    A name the selection assigns before reading it is its own; one that holds a
    function, a class or an import is reached the way the original code reached
    it rather than passed in.
    """
    augmented = {statement.target for node in statements for statement in ast.walk(node)
                 if isinstance(statement, ast.AugAssign)}
    assigned: set[str] = set()
    found: list[str] = []
    for node in _mentioned_names(statements):
        reads = not isinstance(node.ctx, ast.Store) or node in augmented
        if reads and node.id not in assigned and node.id not in found \
                and _set_outside(node.id, scope, span):
            found.append(node.id)
        if isinstance(node.ctx, ast.Store):
            assigned.add(node.id)
    return found


def _results(analysis: Analysis, statements: list[ast.stmt], span: Span) -> list[str]:
    """The names the selection sets that are still read after it, in source order."""
    assigned = dict.fromkeys(node.id for node in _mentioned_names(statements)
                             if isinstance(node.ctx, ast.Store))
    return [name for name in assigned if _read_after(analysis, name, span)]


def _set_outside(name: str, scope: Scope, span: Span) -> bool:
    """Whether ``name`` already holds a value the selection did not put there."""
    bindings = scope.lookup(name, span.line)
    return bool(bindings) and all(
        not binding.imported and binding.definition().type in ("statement", "param")
        and not span.holds(binding.line)
        for binding in bindings)


def _read_after(analysis: Analysis, name: str, span: Span) -> bool:
    """Whether anything below the selection reads what the selection wrote."""
    module = analysis.module.scope
    for line, _column, found in all_names(analysis.tree):
        if found.name != name or line <= span.end_line or defines(found.node):
            continue
        if any(span.holds(definition.line) and definition.module_path == analysis.info.path
               for definition in resolve(found, module.innermost(line), line, follow=True)):
            return True
    return False


def _mentioned_names(statements: list[ast.stmt]) -> Iterator[ast.Name]:
    """Every name the selected statements mention, in the order they are written."""
    found = [node for statement in statements for node in ast.walk(statement)
             if isinstance(node, ast.Name)]
    return iter(sorted(found, key=lambda node: (node.lineno, node.col_offset)))


def _indentation(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]
