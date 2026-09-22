"""Answering `infer` and `goto` for the identifier under a cursor.

`goto` reports the bindings the cursor's name was written at; `infer` reports
what that name evaluates to. Both start from the same identifier lookup, so a
cursor that is not on a name fails the same way for either command.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from .analysis import (
    FUNCTION_NODES,
    Analyzer,
    SourceClass,
    SourceFunction,
    definitions_of,
    identifier_column,
    merged,
)
from .context import cursor_indent
from .definitions import payload
from .narrowing import narrowed_lookup
from .runtime import Value
from .source import Source, SourceError
from .symbols import Symbol


@dataclass
class Query:
    """A cursor resolved to an identifier and the names in scope around it."""

    analyzer: Analyzer
    node: ast.AST
    """The identifier node the cursor sits on."""
    parents: Tuple[ast.AST, ...]
    visible: Dict[str, List[Symbol]]
    lookup: Callable[[str], Optional[Symbol]]

    @classmethod
    def at(cls, source: Source, line: int, col: int) -> "Query":
        """Read the query a cursor position asks, or fail if it is not on a name."""
        indent = cursor_indent(source.line_at(line, col), col)
        found = name_at(source.tree, source.lines, line, col)
        if found is None:
            raise SourceError(f"no name at line {line}, column {col}")
        analyzer = Analyzer(source)
        visible = analyzer.visible(line, indent)
        node, parents = found
        return cls(analyzer, node, parents, visible, narrowed_lookup(analyzer, visible, line, indent))


def infer(source: Source, line: int, col: int) -> str:
    """What the name at the cursor evaluates to, as a JSON document."""
    query = Query.at(source, line, col)
    value = VALUES[type(query.node)](query)
    return payload(value.definitions() if value is not None else [])


def goto(source: Source, line: int, col: int) -> str:
    """Where the name at the cursor was defined, as a JSON document."""
    query = Query.at(source, line, col)
    bindings = BINDINGS[type(query.node)](query)
    return payload([
        definition for symbol in bindings for definition in definitions_of(symbol)
    ])


# --------------------------------------------------------------------------
# Finding the identifier under the cursor
# --------------------------------------------------------------------------


def name_at(tree: ast.Module, lines: List[str], line: int, col: int):
    """The innermost identifier covering a position, with its enclosing nodes."""
    best, width = None, None
    for node, parents in _walk(tree):
        span = SPANS.get(type(node))
        if span is None:
            continue
        found, start, end = span(node, lines)
        if found == line and start <= col <= end and (width is None or end - start <= width):
            best, width = (node, parents), end - start
    return best


def _walk(node: ast.AST, parents: Tuple[ast.AST, ...] = ()) -> Iterator[Tuple[ast.AST, Tuple]]:
    """Every node of a tree, outermost first, with the chain enclosing it."""
    chain = parents + (node,)
    for child in ast.iter_child_nodes(node):
        yield child, chain
        yield from _walk(child, chain)


def bound_name(alias: ast.alias) -> str:
    """The name an import alias binds."""
    return alias.asname or alias.name.split(".")[0]


def _name_span(node, lines):
    return node.lineno, node.col_offset, node.end_col_offset


def _attribute_span(node, lines):
    """The attribute identifier, which ends the expression it belongs to."""
    return node.end_lineno, node.end_col_offset - len(node.attr), node.end_col_offset


def _definition_span(node, lines):
    column = identifier_column(lines, node, node.name)
    return node.lineno, column, column + len(node.name)


def _parameter_span(node, lines):
    return node.lineno, node.col_offset, node.col_offset + len(node.arg)


def _alias_span(node, lines):
    name = bound_name(node)
    if node.asname:
        return node.end_lineno, node.end_col_offset - len(name), node.end_col_offset
    return node.lineno, node.col_offset, node.col_offset + len(name)


SPANS = {
    ast.Name: _name_span,
    ast.Attribute: _attribute_span,
    ast.FunctionDef: _definition_span,
    ast.AsyncFunctionDef: _definition_span,
    ast.ClassDef: _definition_span,
    ast.arg: _parameter_span,
    ast.alias: _alias_span,
}


# --------------------------------------------------------------------------
# What the identifier evaluates to
# --------------------------------------------------------------------------


def _expression_value(query: Query) -> Optional[Value]:
    return query.analyzer.resolve(query.node, query.lookup)


def _function_value(query: Query) -> Value:
    return SourceFunction(query.analyzer, query.node)


def _class_value(query: Query) -> Value:
    return SourceClass(query.analyzer, query.node)


def _parameter_value(query: Query) -> Optional[Value]:
    symbol = merged(_parameter_bindings(query))
    return symbol.value if symbol is not None else None


def _alias_value(query: Query) -> Optional[Value]:
    symbol = query.lookup(bound_name(query.node))
    return symbol.value if symbol is not None else None


VALUES = {
    ast.Name: _expression_value,
    ast.Attribute: _expression_value,
    ast.FunctionDef: _function_value,
    ast.AsyncFunctionDef: _function_value,
    ast.ClassDef: _class_value,
    ast.arg: _parameter_value,
    ast.alias: _alias_value,
}


# --------------------------------------------------------------------------
# Where the identifier was bound
# --------------------------------------------------------------------------


def _name_bindings(query: Query) -> List[Symbol]:
    return query.visible.get(query.node.id, [])


def _attribute_bindings(query: Query) -> List[Symbol]:
    """The members of the receiver that carry the attribute's name."""
    owner = query.analyzer.resolve(query.node.value, query.lookup)
    return owner.attributes(query.node.attr) if owner is not None else []


def _definition_bindings(query: Query) -> List[Symbol]:
    """A `def` or `class` under the cursor is its own binding."""
    scope = query.analyzer.scope_of(query.node).parent
    return [symbol for symbol in query.analyzer.bindings(scope) if symbol.node is query.node]


def _parameter_bindings(query: Query) -> List[Symbol]:
    function = next(
        (node for node in reversed(query.parents) if isinstance(node, FUNCTION_NODES)), None
    )
    if function is None:
        return []
    scope = query.analyzer.scope_of(function)
    return [symbol for symbol in query.analyzer.bindings(scope) if symbol.node is query.node]


def _alias_bindings(query: Query) -> List[Symbol]:
    return query.visible.get(bound_name(query.node), [])


BINDINGS = {
    ast.Name: _name_bindings,
    ast.Attribute: _attribute_bindings,
    ast.FunctionDef: _definition_bindings,
    ast.AsyncFunctionDef: _definition_bindings,
    ast.ClassDef: _definition_bindings,
    ast.arg: _parameter_bindings,
    ast.alias: _alias_bindings,
}
