"""Resolving names and expressions to the things they refer to.

A *target* is whatever a piece of source denotes -- a module, a class, an
instance, a function.  Targets know how to list their attributes, which is what
completion after a `.` needs, and they carry the kind and type name that the
`type` and `description` output fields are built from.
"""

from __future__ import annotations

import ast
import builtins

from . import scopes
from .modules import LocalModule, ModuleIndex, RuntimeModule
from .symbols import CLASS, FUNCTION, INSTANCE, MODULE, PARAM, STATEMENT, Symbol, classify

_MISSING = object()

#: Literal syntax that pins down a builtin type without any name resolution.
_LITERAL_TYPES = {
    ast.List: list,
    ast.ListComp: list,
    ast.Dict: dict,
    ast.DictComp: dict,
    ast.Set: set,
    ast.SetComp: set,
    ast.Tuple: tuple,
    ast.JoinedStr: str,
}


class Target:
    """Something a name can refer to."""

    kind = STATEMENT
    type_name: str | None = None

    def attributes(self) -> list[Symbol]:
        return []

    def attribute(self, name: str) -> "Target | None":
        return None

    def called(self) -> "Target | None":
        """The target of calling this one, i.e. instantiating a class."""
        return None


class RuntimeTarget(Target):
    """A live object reached through an imported module or through builtins."""

    def __init__(self, obj: object) -> None:
        self.obj = obj
        self.kind = classify(obj)
        self.type_name = type(obj).__name__

    def attributes(self) -> list[Symbol]:
        names = dir(self.obj)
        if self.kind == MODULE:
            names = [name for name in names if not name.startswith("_")]
        return [Symbol.from_object(name, getattr(self.obj, name, None)) for name in names]

    def attribute(self, name: str) -> Target | None:
        member = getattr(self.obj, name, _MISSING)
        return None if member is _MISSING else RuntimeTarget(member)

    def called(self) -> Target | None:
        return RuntimeInstanceTarget(self.obj) if self.kind == CLASS else None


class RuntimeInstanceTarget(Target):
    """An instance of a live class, such as a literal or `list()`."""

    kind = INSTANCE

    def __init__(self, cls: type) -> None:
        self.cls = cls
        self.type_name = cls.__name__

    def attributes(self) -> list[Symbol]:
        return [Symbol.from_object(name, getattr(self.cls, name, None)) for name in dir(self.cls)]

    def attribute(self, name: str) -> Target | None:
        member = getattr(self.cls, name, _MISSING)
        return None if member is _MISSING else RuntimeTarget(member)


class ModuleTarget(Target):
    """An imported module, whether a project file or an installed package."""

    kind = MODULE

    def __init__(self, handle, resolver: "Resolver") -> None:
        self.handle = handle
        self.resolver = resolver

    def attributes(self) -> list[Symbol]:
        return self.resolver.module_symbols(self.handle)

    def attribute(self, name: str) -> Target | None:
        return self.resolver.member_target(self.handle, name)


class ClassTarget(Target):
    """A class defined in the file being analysed."""

    kind = CLASS

    def __init__(self, node: ast.ClassDef, resolver: "Resolver") -> None:
        self.node = node
        self.resolver = resolver

    def attributes(self) -> list[Symbol]:
        return self.resolver.class_symbols(self.node)

    def attribute(self, name: str) -> Target | None:
        return self.resolver.class_member(self.node, name)

    def called(self) -> Target:
        return InstanceTarget(self.node, self.resolver)


class InstanceTarget(Target):
    """An instance of a class defined in the file being analysed."""

    kind = INSTANCE

    def __init__(self, node: ast.ClassDef, resolver: "Resolver") -> None:
        self.node = node
        self.resolver = resolver
        self.type_name = node.name

    def attributes(self) -> list[Symbol]:
        return self.resolver.instance_symbols(self.node)

    def attribute(self, name: str) -> Target | None:
        return self.resolver.class_member(self.node, name)


class FunctionTarget(Target):
    """A function or method defined in the file being analysed."""

    kind = FUNCTION

    def __init__(self, node: ast.AST) -> None:
        self.node = node


class Resolver:
    """Answers "what is this?" for the names and expressions of one file."""

    def __init__(self, tree: scopes.ScopeTree, modules: ModuleIndex, siblings=None) -> None:
        self.tree = tree
        self.modules = modules
        self._siblings = {} if siblings is None else siblings
        self._active: set[int] = set()

    # -- expressions ---------------------------------------------------

    def expression(self, node: ast.expr | None, scope: scopes.Scope) -> Target | None:
        literal = _LITERAL_TYPES.get(type(node))
        if literal is not None:
            return RuntimeInstanceTarget(literal)
        if isinstance(node, ast.Constant):
            return RuntimeInstanceTarget(type(node.value))
        if isinstance(node, ast.Name):
            return self.name(node.id, scope)
        if isinstance(node, ast.Attribute):
            base = self.expression(node.value, scope)
            return base.attribute(node.attr) if base else None
        if isinstance(node, ast.Call):
            func = self.expression(node.func, scope)
            return func.called() if func else None
        return None

    def source(self, text: str, scope: scopes.Scope) -> Target | None:
        """Resolve a snippet of source, such as the receiver before a dot."""
        try:
            expression = ast.parse(text, mode="eval").body
        except SyntaxError:
            return None
        return self.expression(expression, scope)

    def name(self, name: str, scope: scopes.Scope) -> Target | None:
        for current in scopes.lookup_chain(scope):
            binding = _last_binding(current, name)
            if binding is not None:
                return self.binding(binding)
        member = getattr(builtins, name, _MISSING)
        return None if member is _MISSING else RuntimeTarget(member)

    # -- bindings ------------------------------------------------------

    def binding(self, binding: scopes.Binding) -> Target | None:
        """What the name introduced by `binding` refers to."""
        if id(binding.node) in self._active:
            return None  # self-referential assignment such as `x = x`
        self._active.add(id(binding.node))
        try:
            return self._binding_target(binding)
        finally:
            self._active.discard(id(binding.node))

    def _binding_target(self, binding: scopes.Binding) -> Target | None:
        form, scope = binding.form, binding.owner
        if form == scopes.DEF:
            return FunctionTarget(binding.node)
        if form == scopes.CLASS:
            return ClassTarget(binding.node, self)
        if form == scopes.IMPORT:
            return self.module_target(binding.module)
        if form == scopes.FROM_IMPORT:
            return self.imported_member(binding.module, binding.node.name)
        if form == scopes.PARAM:
            return self._param_target(binding)
        if binding.annotation is not None or form == scopes.EXCEPT:
            return self._instance_of(binding.annotation or binding.value, scope)
        return self.expression(binding.value, scope)

    def _param_target(self, binding: scopes.Binding) -> Target | None:
        owner = binding.owner
        if binding.name == "self" and owner.parent is not None and owner.parent.kind == "class":
            return InstanceTarget(owner.parent.node, self)
        return self._instance_of(binding.annotation, binding.owner)

    def _instance_of(self, annotation: ast.expr | None, scope: scopes.Scope) -> Target | None:
        """Turn a type expression (an annotation, an except clause) into an instance."""
        target = self.expression(annotation, scope)
        return target.called() if target else None

    def symbol(self, binding: scopes.Binding) -> Symbol:
        """The completion record for a bound name."""
        simple = _SIMPLE_KINDS.get(binding.form)
        if simple is not None:
            return Symbol.of(binding.name, simple)
        return name_symbol(binding.name, self.binding(binding))

    # -- modules -------------------------------------------------------

    def module_target(self, dotted: str) -> Target | None:
        handle = self.modules.resolve(dotted)
        return ModuleTarget(handle, self) if handle else None

    def imported_member(self, dotted: str, name: str) -> Target | None:
        """Resolve `from <dotted> import <name>`, which may itself be a module."""
        handle = self.modules.resolve(dotted)
        member = self.member_target(handle, name) if handle else None
        return member or self.module_target(f"{dotted}.{name}" if dotted else name)

    def member_target(self, handle, name: str) -> Target | None:
        if isinstance(handle, RuntimeModule):
            member = getattr(handle.module, name, _MISSING)
            return None if member is _MISSING else RuntimeTarget(member)
        resolver, tree = self._sibling(handle)
        binding = _last_binding(tree.root, name)
        return resolver.binding(binding) if binding else None

    def module_symbols(self, handle) -> list[Symbol]:
        """The public names of a module, as completion records."""
        if isinstance(handle, RuntimeModule):
            module = handle.module
            return [
                Symbol.from_object(name, getattr(module, name, None))
                for name in dir(module)
                if not name.startswith("_")
            ]
        resolver, tree = self._sibling(handle)
        return [
            resolver.symbol(binding)
            for binding in _distinct(tree.root.bindings)
            if not binding.name.startswith("_")
        ]

    def _sibling(self, handle: LocalModule):
        """The resolver and scope tree of a project module, built on first use."""
        if handle.name not in self._siblings:
            tree = scopes.build(handle.tree)
            self._siblings[handle.name] = (Resolver(tree, self.modules, self._siblings), tree)
        return self._siblings[handle.name]

    # -- classes -------------------------------------------------------

    def linearize(self, node: ast.ClassDef) -> list[ast.ClassDef]:
        """`node` followed by its base classes that are defined in this file."""
        order: list[ast.ClassDef] = []
        pending = [node]
        while pending:
            klass = pending.pop(0)
            if any(klass is seen for seen in order):
                continue
            order.append(klass)
            pending.extend(
                self.tree.classes[base.id]
                for base in klass.bases
                if isinstance(base, ast.Name) and base.id in self.tree.classes
            )
        return order

    def class_symbols(self, node: ast.ClassDef) -> list[Symbol]:
        """Class attributes and methods, including inherited in-file ones."""
        symbols: dict[str, Symbol] = {}
        for klass in self.linearize(node):
            for binding in _distinct(self.tree.scope_for(klass).bindings):
                symbols.setdefault(binding.name, self.symbol(binding))
        return list(symbols.values())

    def instance_symbols(self, node: ast.ClassDef) -> list[Symbol]:
        """Class attributes plus whatever `__init__` assigns onto `self`."""
        symbols = {symbol.name: symbol for symbol in self.class_symbols(node)}
        for klass in self.linearize(node):
            for name, value, annotation, scope in self._init_assignments(klass):
                symbols.setdefault(
                    name, name_symbol(name, self.expression(annotation or value, scope))
                )
        return list(symbols.values())

    def class_member(self, node: ast.ClassDef, name: str) -> Target | None:
        for klass in self.linearize(node):
            binding = _last_binding(self.tree.scope_for(klass), name)
            if binding is not None:
                return self.binding(binding)
        return None

    def _init_assignments(self, klass: ast.ClassDef):
        """Yield (name, value, annotation, scope) for each `self.x = ...` in `__init__`."""
        for statement in klass.body:
            if not isinstance(statement, scopes.FUNCTION_NODES) or statement.name != "__init__":
                continue
            scope = self.tree.scope_for(statement)
            for node in ast.walk(statement):
                targets = _assignment_targets(node)
                for target in targets:
                    if _is_self_attribute(target):
                        yield target.attr, node.value, getattr(node, "annotation", None), scope


def name_symbol(name: str, target: Target | None) -> Symbol:
    """Describe `name` given what it was resolved to."""
    if target is None:
        return Symbol.of(name, STATEMENT)
    return Symbol.of(name, target.kind, target.type_name)


#: Binding forms whose completion type never depends on resolution.
_SIMPLE_KINDS = {
    scopes.DEF: FUNCTION,
    scopes.CLASS: CLASS,
    scopes.PARAM: PARAM,
    scopes.IMPORT: MODULE,
}


def _last_binding(scope: scopes.Scope, name: str) -> scopes.Binding | None:
    return next((b for b in reversed(scope.bindings) if b.name == name), None)


def _distinct(bindings: list[scopes.Binding]) -> list[scopes.Binding]:
    """The latest binding for each name, in first-appearance order."""
    latest = {binding.name: binding for binding in bindings}
    return list(latest.values())


def _assignment_targets(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return node.targets
    if isinstance(node, ast.AnnAssign):
        return [node.target]
    return []


def _is_self_attribute(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )
