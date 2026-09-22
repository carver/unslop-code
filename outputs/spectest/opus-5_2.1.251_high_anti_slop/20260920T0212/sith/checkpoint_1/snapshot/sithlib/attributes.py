"""Resolving what a receiver expression offers after a dot."""

import ast

from . import symbols
from .inference import assignment_symbol, type_name
from .runtime import attributes_of, resolve_expression


class AttributeResolver:
    """Answers ``what can follow this dot?`` for one analysed module."""

    def __init__(self, index):
        self._index = index

    def resolve(self, receiver, visible):
        """Symbols for the attributes of `receiver`, given the names in scope."""
        local_class, is_instance = self._local_class(receiver, visible)
        if local_class is not None:
            return list(self._members(local_class, is_instance).values())
        live = self._live_object(receiver, visible)
        return attributes_of(live) if live is not None else []

    def _local_class(self, receiver, visible):
        """The class defined in this file that a receiver refers to.

        Returns the class node and whether the receiver is an instance of it
        rather than the class itself.
        """
        if isinstance(receiver, ast.Name) and receiver.id in self._index.classes:
            return self._index.classes[receiver.id], False
        return self._index.classes.get(self._held_type(receiver, visible)), True

    def _held_type(self, receiver, visible):
        """Name of the type the receiver holds, via the scope or the expression."""
        if isinstance(receiver, ast.Name):
            symbol = visible.get(receiver.id)
            return symbol.type_name if symbol is not None else None
        return type_name(receiver, self._index)

    def _live_object(self, receiver, visible):
        """The imported, builtin or builtin-typed object a receiver evaluates to."""
        if isinstance(receiver, ast.Attribute):
            return resolve_expression(receiver, self._index.lookup)
        held = self._held_type(receiver, visible)
        if held is not None:
            return self._index.lookup(held)
        return self._index.lookup(receiver.id) if isinstance(receiver, ast.Name) else None

    def _members(self, node, include_instance):
        """Members of a class body plus those of its bases defined in this file."""
        members = {}
        for base in self._bases(node):
            members.update(self._members(base, include_instance))
        for statement in node.body:
            members.update(self._declared(statement))
        if include_instance:
            members.update(self._instance_attributes(node))
        return members

    def _bases(self, node):
        return [
            self._index.classes[base.id]
            for base in node.bases
            if isinstance(base, ast.Name) and base.id in self._index.classes
        ]

    def _declared(self, statement):
        """Name -> symbol for a single statement of a class body."""
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return {statement.name: symbols.function(statement.name, statement.lineno)}
        if isinstance(statement, ast.ClassDef):
            return {statement.name: symbols.klass(statement.name, statement.lineno)}
        return {
            target.id: self._assigned(target.id, value, annotation, statement.lineno)
            for target, value, annotation in _assignments(statement)
            if isinstance(target, ast.Name)
        }

    def _instance_attributes(self, node):
        """Attributes a class assigns to its receiver inside ``__init__``."""
        initializer = next(
            (
                statement
                for statement in node.body
                if isinstance(statement, ast.FunctionDef) and statement.name == "__init__"
            ),
            None,
        )
        if initializer is None:
            return {}
        receiver = _receiver_name(initializer)
        return {
            target.attr: self._assigned(target.attr, value, annotation, statement.lineno)
            for statement in ast.walk(initializer)
            for target, value, annotation in _assignments(statement)
            if isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == receiver
        }

    def _assigned(self, name, value, annotation, lineno):
        return assignment_symbol(name, value, lineno, self._index, annotation)


def _assignments(statement):
    """The (target, value, annotation) triples a statement assigns, ignoring unpacking."""
    if isinstance(statement, ast.Assign):
        return [(target, statement.value, None) for target in statement.targets]
    if isinstance(statement, ast.AnnAssign):
        return [(statement.target, statement.value, statement.annotation)]
    return []


def _receiver_name(initializer):
    """The name ``__init__`` gives its instance parameter, usually ``self``."""
    declared = initializer.args.posonlyargs + initializer.args.args
    return declared[0].arg if declared else None
