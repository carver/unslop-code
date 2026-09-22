"""The `extract-variable` and `extract-function` commands."""

import ast

from . import dataflow
from .edits import Edit, collect
from .modules import project_at
from .selections import (check_identifier, enclosing_statement, expression_at,
                         span_of, statements_at)
from .source import span_text

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_BODY = "    "


def extract_variable(path, line, column, until, name, options):
    """Bind the selected expression to a new variable and use the variable instead."""
    check_identifier(name)
    project = project_at(options)
    module = project.module(path)
    span = span_of(line, column, until)
    statement = enclosing_statement(module.tree, expression_at(module.tree, span))
    above = _start_line(statement)
    indent = _indentation(module.lines, above)
    selected = span_text(module.lines, span.line, span.column,
                         span.until_line, span.until_column)
    return collect(project, [
        Edit(module.path, above, 0, above, 0, f"{indent}{name} = {selected}\n"),
        Edit(module.path, span.line, span.column, span.until_line, span.until_column, name),
    ])


def extract_function(path, line, column, until, name, options):
    """Move the selected statements into a new function and call it in their place."""
    check_identifier(name)
    project = project_at(options)
    module = project.module(path)
    span = span_of(line, column, until)
    statements = statements_at(module.tree, module.lines, span)
    host = _enclosing_function(module.tree, span)
    parameters = dataflow.parameters(module, statements, span)
    results = dataflow.results(module, statements, span, host)
    indent = _indentation(module.lines, span.line)
    outer = indent if host is None else _indentation(module.lines, _start_line(host))
    definition = _definition(module, span, name, parameters, results, outer)
    call = f"{indent}{_receiving(results)}{name}({', '.join(parameters)})\n"
    return collect(project, _placed(module, span, host, definition, call))


def _placed(module, span, host, definition, call):
    """The edits writing the new function and replacing the statements it took.

    A function extracted at module level goes exactly where its statements sat,
    kept apart from the code above it; one taken out of a function goes above
    that function, decorators included.
    """
    if host is None:
        above = module.lines[span.line - 2] if span.line > 1 else ""
        lead = _spacing(_indentation(module.lines, span.line)) if above.strip() else ""
        return [Edit(module.path, span.line, 0, span.until_line + 1, 0,
                     lead + definition + call)]
    line = _start_line(host)
    return [
        Edit(module.path, line, 0, line, 0, definition),
        Edit(module.path, span.line, 0, span.until_line + 1, 0, call),
    ]


def _definition(module, span, name, parameters, results, indent):
    """The source of the extracted function, with the blank lines that follow it."""
    inner = len(_indentation(module.lines, span.line))
    body = [f"{indent}def {name}({', '.join(parameters)}):"]
    body += [f"{indent}{_BODY}{text[inner:]}" if text.strip() else ""
             for text in module.lines[span.line - 1:span.until_line]]
    if results:
        body.append(f"{indent}{_BODY}return {', '.join(results)}")
    return "\n".join(body) + "\n" + _spacing(indent)


def _spacing(indent):
    """The blank lines that keep a definition apart from its neighbours."""
    return "\n" if indent else "\n\n"


def _receiving(results):
    """The assignment the call site opens with, unpacking several results at once."""
    return f"{', '.join(results)} = " if results else ""


def _enclosing_function(tree, span):
    """The innermost function holding the selection, or ``None`` at module level."""
    holders = [node for node in ast.walk(tree) if isinstance(node, _FUNCTIONS)
               and node.lineno <= span.line and span.until_line <= node.end_lineno]
    return max(holders, key=lambda node: node.lineno, default=None)


def _start_line(node):
    """The line a statement starts at, counting the decorators written above it."""
    return min([node.lineno] + [item.lineno for item in getattr(node, "decorator_list", [])])


def _indentation(lines, line):
    text = lines[line - 1]
    return text[:len(text) - len(text.lstrip())]
