"""The attributes a class offers: its body, its bases and its instance state."""

import ast

from .bindings import ASSIGN, Binding, Reference
from .modules import Context
from .values import ClassValue

_METHODS = (ast.FunctionDef, ast.AsyncFunctionDef)


def members(evaluator, value):
    """Name -> reference for every attribute a class value exposes.

    Names declared in the class body come first for the class itself; an
    instance additionally exposes whatever its methods assign to ``self``.
    """
    found = {}
    for base in bases(evaluator, value):
        found.update(members(evaluator, base))
    found.update(_declared(value))
    if value.instance:
        found.update(_instance_state(value))
    return found


def bases(evaluator, value):
    """The base classes of a class value, inferred in the module that defines it."""
    context = Context(value.module, value.node.lineno, value.node.col_offset)
    return [
        ClassValue(inferred.module, inferred.node, value.instance)
        for base in value.node.bases
        for inferred in evaluator.infer(base, context)
        if isinstance(inferred, ClassValue)
    ]


def _declared(value):
    """The names the class body binds, keeping the last binding of each name."""
    scope = value.module.scope_for(value.node)
    return {
        name: Reference(value.module, bound[-1])
        for name, bound in scope.declared().items()
    }


def _instance_state(value):
    """The attributes the methods of a class assign to their receiver.

    The first assignment of a name wins: that is where the attribute is
    introduced, which is usually ``__init__`` rather than a later method.
    """
    found = {}
    for method in value.node.body:
        if isinstance(method, _METHODS):
            for name, reference in _assigned_to_receiver(value, method).items():
                found.setdefault(name, reference)
    return found


def _assigned_to_receiver(value, method):
    receiver = _receiver_name(method)
    return {
        target.attr: Reference(value.module, _attribute(value.node, statement, target, assigned,
                                                        annotation))
        for statement in ast.walk(method)
        for target, assigned, annotation in assignments(statement)
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == receiver
    }


def _attribute(owner, statement, target, value, annotation):
    return Binding(
        name=target.attr,
        kind=ASSIGN,
        node=statement,
        lineno=target.end_lineno,
        column=target.end_col_offset - len(target.attr),
        value=value,
        annotation=annotation,
        owner=owner,
    )


def _receiver_name(method):
    """The name a method gives its instance parameter, usually ``self``."""
    declared = method.args.posonlyargs + method.args.args
    return declared[0].arg if declared else None


def assignments(statement):
    """The (target, value, annotation) triples a statement assigns."""
    if isinstance(statement, ast.Assign):
        return [(target, statement.value, None) for target in statement.targets]
    if isinstance(statement, ast.AnnAssign):
        return [(statement.target, statement.value, statement.annotation)]
    return []
