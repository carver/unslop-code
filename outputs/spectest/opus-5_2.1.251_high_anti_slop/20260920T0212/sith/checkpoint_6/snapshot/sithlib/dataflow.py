"""Which names a run of statements reads from around it, and which ones it hands back."""

import ast

from .bindings import ASSIGN, EXCEPT, PARAM, TARGET
from .scopes import enclosing_chain, innermost

_VARIABLES = (ASSIGN, TARGET, PARAM, EXCEPT)

# Fields whose evaluation order differs from the order they are written in.
_EVALUATED = {
    ast.Assign: ("value", "targets"),
    ast.AnnAssign: ("annotation", "value", "target"),
    ast.For: ("iter", "target", "body", "orelse"),
    ast.AsyncFor: ("iter", "target", "body", "orelse"),
    ast.comprehension: ("iter", "target", "ifs"),
    ast.ListComp: ("generators", "elt"),
    ast.SetComp: ("generators", "elt"),
    ast.GeneratorExp: ("generators", "elt"),
    ast.DictComp: ("generators", "key", "value"),
}


def parameters(module, statements, span):
    """The names the statements read from their surroundings, first use first.

    A name the statements bind before reading holds a value of their own and
    needs no parameter; one they read first is taken from the code around them.
    """
    outer = _outer_variables(module, span)
    found, bound = [], set()
    for name, reads in _events(statements):
        if not reads:
            bound.add(name)
        elif name in outer and name not in bound:
            found.append(name)
    return list(dict.fromkeys(found))


def results(module, statements, span, host):
    """The names the statements bind that the code after them still reads."""
    later = _read_after(host if host is not None else module.tree, span)
    bound = dict.fromkeys(name for name, reads in _events(statements) if not reads)
    return [name for name in bound if name in later]


def _events(statements):
    """(name, reads) pairs for the names the statements touch, as they run."""
    for statement in statements:
        yield from _touched(statement)


def _touched(node):
    """The names one node touches, reading before binding where that is the order.

    An augmented assignment reads its target before rebinding it, so its name
    is reported twice.
    """
    if isinstance(node, ast.Name):
        yield node.id, isinstance(node.ctx, ast.Load)
        return
    if isinstance(node, ast.AugAssign):
        yield from _touched(node.value)
        yield node.target.id, True
        yield from _touched(node.target)
        return
    for child in _children(node):
        yield from _touched(child)


def _children(node):
    """The child nodes of `node`, in the order the code evaluates them."""
    names = _EVALUATED.get(type(node))
    fields = ([getattr(node, name) for name in names] if names
              else [value for _, value in ast.iter_fields(node)])
    for field in fields:
        for child in (field if isinstance(field, list) else [field]):
            if isinstance(child, ast.AST):
                yield child


def _outer_variables(module, span):
    """The variables bound around the selection, ignoring the ones inside it."""
    text = module.lines[span.line - 1]
    scope = innermost(module.scope, span.line, len(text) - len(text.lstrip()))
    return {
        binding.name
        for holder in enclosing_chain(scope)
        for binding in holder.bindings
        if binding.kind in _VARIABLES and not span.line <= binding.lineno <= span.until_line
    }


def _read_after(region, span):
    """The names read below the selection, inside the code holding it."""
    return {node.id for node in ast.walk(region)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            and node.lineno > span.until_line}
