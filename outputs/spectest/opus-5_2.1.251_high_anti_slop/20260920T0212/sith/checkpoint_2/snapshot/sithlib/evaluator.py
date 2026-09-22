"""Inferring what expressions evaluate to and where their names are defined."""

import ast

from . import classes, narrowing, symbols
from .bindings import ASSIGN, CLASS, EXCEPT, FUNCTION, IMPORT, PARAM, Reference
from .imports import ImportResolver
from .modules import Context
from .runtime import builtin_objects, builtin_type, live_members
from .scopes import STAR, visible_bindings
from .values import (NONE, BuiltinValue, ClassValue, FunctionValue, LiveValue,
                     ModuleValue, instantiate)

_LITERAL_TYPES = {
    ast.List: "list",
    ast.ListComp: "list",
    ast.Dict: "dict",
    ast.DictComp: "dict",
    ast.Set: "set",
    ast.SetComp: "set",
    ast.Tuple: "tuple",
    ast.GeneratorExp: "generator",
    ast.JoinedStr: "str",
    ast.Compare: "bool",
}

_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class Evaluator:
    """Answers what a name holds, and where it came from, across one project.

    Inference returns every possibility it can reach: a name assigned in two
    branches yields two values, and an unresolvable one yields none.
    """

    def __init__(self, project):
        self._project = project
        self._imports = ImportResolver(self, project)
        self._active = set()
        self._expressions = {
            ast.Name: self._name,
            ast.Attribute: self._attribute,
            ast.Call: self._call,
            ast.Constant: self._constant,
            ast.IfExp: self._choice,
            ast.BoolOp: self._choice,
            ast.Await: self._awaited,
            ast.NamedExpr: self._awaited,
        }
        self._bindings = {
            CLASS: lambda binding, context: [ClassValue(context.module, binding.node)],
            FUNCTION: lambda binding, context: [FunctionValue(context.module, binding.node)],
            PARAM: self._parameter,
            IMPORT: self._imports.values,
            ASSIGN: self._assigned,
            EXCEPT: self._raised,
        }

    # Expressions ---------------------------------------------------------

    def infer(self, node, context):
        """Every value the expression `node` can evaluate to at `context`."""
        handler = self._expressions.get(type(node))
        if handler is not None:
            return handler(node, context)
        literal = _LITERAL_TYPES.get(type(node))
        return [BuiltinValue(literal)] if literal is not None else []

    def infer_name(self, name, context):
        """Every value `name` can hold, after the tests guarding the cursor line."""
        values = [value for entry in self.lookup(name, context)
                  for value in self.entry_values(entry)]
        return self._narrowed(name, values, context)

    def instances(self, values):
        """The instances produced by calling each value that is a class."""
        produced = (instantiate(value) for value in values)
        return [value for value in produced if value is not None]

    # Names ---------------------------------------------------------------

    def lookup(self, name, context):
        """What `name` refers to at `context`: bindings first, then builtins."""
        visible = visible_bindings(context.module.scope, context.line, context.indent)
        if name in visible:
            return [Reference(context.module, binding) for binding in visible[name]]
        imported = self._starred(name, visible.get(STAR, []), context)
        if imported:
            return imported
        available = builtin_objects()
        if name not in available:
            return []
        return [LiveValue(self._project, name, available[name])]

    def visible_entries(self, context):
        """Name -> entry for every name the cursor can see, nearest binding winning."""
        entries = {
            name: LiveValue(self._project, name, obj)
            for name, obj in builtin_objects().items()
        }
        visible = visible_bindings(context.module.scope, context.line, context.indent)
        for binding in visible.get(STAR, []):
            entries.update(self._imports.star_members(binding, context))
        entries.update(
            (name, Reference(context.module, bound[-1]))
            for name, bound in visible.items()
            if name != STAR
        )
        return entries

    def entry_values(self, entry):
        """The values an entry holds; entries are either bindings or values."""
        return self.infer_reference(entry) if isinstance(entry, Reference) else [entry]

    def entry_display(self, entry):
        """The type and description a completion shows for an entry.

        A name is shown as what it holds - ``instance of Dog`` - falling back
        to the statement that binds it when nothing can be inferred.
        """
        values = self.entry_values(entry)
        shown = values[0].definition() if values else self.entry_definition(entry)
        return shown.type, shown.description

    def entry_definition(self, entry):
        """The definition record an entry prints."""
        if not isinstance(entry, Reference):
            return entry.definition()
        binding = entry.binding
        if binding.kind == CLASS:
            return ClassValue(entry.module, binding.node).definition()
        if binding.kind == FUNCTION:
            return FunctionValue(entry.module, binding.node).definition()
        return entry.definition(self._binding_type(entry))

    def infer_reference(self, reference):
        """The values the binding behind a reference holds."""
        binding = reference.binding
        key = (id(binding.node), binding.name)
        if key in self._active:
            return []
        self._active.add(key)
        try:
            handler = self._bindings.get(binding.kind)
            context = Context(reference.module, binding.lineno, binding.column)
            return handler(binding, context) if handler is not None else []
        finally:
            self._active.discard(key)

    # Attributes ----------------------------------------------------------

    def members(self, value):
        """Name -> entry for everything reachable through a dot on `value`."""
        if isinstance(value, ClassValue):
            return classes.members(self, value)
        if isinstance(value, ModuleValue):
            return {
                name: Reference(value.module, bound[-1])
                for name, bound in value.module.scope.declared().items()
                if name != STAR
            }
        live = self._live_object(value)
        if live is None:
            return {}
        return {
            name: LiveValue(self._project, name, obj)
            for name, obj in live_members(live).items()
        }

    def member_entries(self, values, name):
        """The entries a dotted name reaches, one per value that offers it."""
        found = [self.members(value).get(name) for value in values]
        return [entry for entry in found if entry is not None]

    def member_values(self, values, name):
        return [value for entry in self.member_entries(values, name)
                for value in self.entry_values(entry)]

    # Expression handlers -------------------------------------------------

    def _name(self, node, context):
        return self.infer_name(node.id, context)

    def _attribute(self, node, context):
        return self.member_values(self.infer(node.value, context), node.attr)

    def _call(self, node, context):
        produced = []
        for value in self.infer(node.func, context):
            if isinstance(value, FunctionValue):
                produced.extend(self._returned(value))
            else:
                produced.extend(self.instances([value]))
        return produced

    def _constant(self, node, _context):
        if node.value is None:
            return [NONE]
        return [BuiltinValue(type(node.value).__name__)]

    def _choice(self, node, context):
        branches = node.values if isinstance(node, ast.BoolOp) else [node.body, node.orelse]
        return [value for branch in branches for value in self.infer(branch, context)]

    def _awaited(self, node, context):
        return self.infer(node.value, context)

    # Binding handlers ----------------------------------------------------

    def _parameter(self, binding, context):
        """A parameter holds its class, its annotation, or whatever it defaults to."""
        if binding.receiver is not None:
            return [ClassValue(context.module, binding.receiver, instance=True)]
        annotated = self._annotated(binding.annotation, context)
        if annotated or binding.value is None:
            return annotated
        return self.infer(binding.value, context)

    def _assigned(self, binding, context):
        if binding.value is not None:
            return self.infer(binding.value, context)
        return self._annotated(binding.annotation, context)

    def _raised(self, binding, context):
        return self.instances(self.infer(binding.value, context))

    def _annotated(self, annotation, context):
        if annotation is None:
            return []
        return self.instances(self.infer(annotation, context))

    def _starred(self, name, star_bindings, context):
        entries = []
        for binding in star_bindings:
            entry = self._imports.star_members(binding, context).get(name)
            if entry is not None:
                entries.append(entry)
        return entries

    # Supporting detail ---------------------------------------------------

    def _returned(self, value):
        """The values a function hands back, or ``None`` when it returns nothing."""
        key = (id(value.node), "return")
        if key in self._active:
            return []
        self._active.add(key)
        try:
            returns = list(_return_statements(value.node))
            produced = [
                inferred
                for statement in returns
                if statement.value is not None
                for inferred in self.infer(statement.value, Context(value.module,
                                                                    statement.lineno,
                                                                    statement.col_offset))
            ]
            bare = not returns or all(statement.value is None for statement in returns)
            return [NONE] if bare else produced
        finally:
            self._active.discard(key)

    def _narrowed(self, name, values, context):
        for test, taken in narrowing.conditions(context.module.tree, context.line):
            values = self._constrain(name, values, test, taken, context)
        return values

    def _constrain(self, name, values, test, taken, context):
        """Apply one guarding test to what a name is otherwise known to hold."""
        checked = narrowing.checked_class(test, name)
        if checked is not None:
            return self._checked_instances(checked, context) if taken else values
        asserts_none = narrowing.none_check(test, name)
        if asserts_none is None:
            return values
        if asserts_none == taken:
            return [NONE]
        return [value for value in values if value != NONE]

    def _checked_instances(self, node, context):
        """The instances an ``isinstance`` test admits, which may name a tuple."""
        parts = node.elts if isinstance(node, ast.Tuple) else [node]
        return [value for part in parts
                for value in self.instances(self.infer(part, context))]

    def _binding_type(self, reference):
        """The definition type of a binding: what it holds, when that is known."""
        if reference.binding.kind == PARAM:
            return symbols.PARAM
        if reference.binding.kind != IMPORT:
            return symbols.STATEMENT
        values = self.infer_reference(reference)
        return values[0].definition().type if values else symbols.STATEMENT

    def _live_object(self, value):
        if isinstance(value, LiveValue):
            return value.obj
        return builtin_type(value.type_name) if isinstance(value, BuiltinValue) else None


def _return_statements(node):
    """The ``return`` statements of a function, skipping any nested definition."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _DEFINITIONS):
            continue
        if isinstance(child, ast.Return):
            yield child
        else:
            yield from _return_statements(child)
