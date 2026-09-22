"""Resolving names and expressions to the things they refer to.

A name can denote several things at once -- two branches of an `if` may bind it
differently -- so every resolution step yields a list of targets rather than a
single one.  What the targets themselves can do lives in `targets.py`.
"""

from __future__ import annotations

import ast
import builtins

from . import definitions, flow, scopes
from .definitions import Definition
from .modules import RuntimeModule
from .symbols import CLASS, FUNCTION, MODULE, PARAM, STATEMENT, Symbol, describe
from .targets import (
    MISSING,
    ClassTarget,
    FunctionTarget,
    InstanceTarget,
    ModuleTarget,
    RuntimeInstanceTarget,
    RuntimeTarget,
    Target,
    is_none,
)

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


class Resolver:
    """Answers "what is this?" for the names and expressions of one file.

    `position` is the line the request is about: it decides which bindings are
    already in force and which `if` branches the cursor sits inside.  Resolvers
    built for other project files have no position of their own.
    """

    def __init__(self, tree, modules, module, siblings=None, position=None) -> None:
        self.tree = tree
        self.modules = modules
        self.module = module
        self.position = position
        self._siblings = {} if siblings is None else siblings
        self._active: set[int] = set()
        self._attributes: dict[int, list[scopes.Binding]] = {}

    # -- expressions ---------------------------------------------------

    def expression(self, node: ast.expr | None, scope: scopes.Scope) -> list[Target]:
        literal = _LITERAL_TYPES.get(type(node))
        if literal is not None:
            return [RuntimeInstanceTarget(literal)]
        if isinstance(node, ast.Constant):
            return [RuntimeInstanceTarget(type(node.value))]
        if isinstance(node, ast.Name):
            return self.name(node.id, scope)
        if isinstance(node, ast.Attribute):
            bases = self.expression(node.value, scope)
            return [target for base in bases for target in base.attribute(node.attr)]
        if isinstance(node, ast.Call):
            called = self.expression(node.func, scope)
            return [target for func in called for target in func.called()]
        return []

    def source(self, text: str, scope: scopes.Scope) -> list[Target]:
        """Resolve a snippet of source, such as the receiver before a dot."""
        try:
            expression = ast.parse(text, mode="eval").body
        except SyntaxError:
            return []
        return self.expression(expression, scope)

    def name(self, name: str, scope: scopes.Scope) -> list[Target]:
        bindings = self.bindings_for(name, scope)
        found = self.binding_targets(bindings) if bindings else _builtin_target(name)
        return self.narrowed(name, scope, found)

    def binding_at(self, name: str, line: int, column: int) -> list[scopes.Binding]:
        """The binding whose own identifier starts at that position, if any.

        A class body is not part of the lookup chain of the code inside it, so
        a cursor resting on a method or a class attribute is found this way
        rather than by name resolution.
        """
        return [
            binding
            for scope in self.tree.by_node.values()
            for binding in scope.bindings
            if binding.name == name
            and binding.lineno == line
            and definitions.name_column(self.module.lines, binding.node, name) == column
        ]

    def bindings_for(self, name: str, scope: scopes.Scope) -> list[scopes.Binding]:
        """The bindings a bare name can refer to, nearest scope winning."""
        for current in scopes.lookup_chain(scope):
            found = scopes.live_bindings(current, name, self.position)
            if found:
                return found
        return []

    # -- narrowing -----------------------------------------------------

    def narrowed(self, name: str, scope: scopes.Scope, found: list[Target]) -> list[Target]:
        """Apply the `isinstance` and `is None` guards the cursor sits inside."""
        if self.position is None:
            return found
        for constraint in flow.narrowings(self.tree.root.node, name, self.position):
            found = self._constrained(constraint, scope, found)
        return found

    def _constrained(self, constraint, scope: scopes.Scope, found: list[Target]) -> list[Target]:
        if constraint.types:
            return self.instances(constraint.types, scope)
        if constraint.none:
            return [RuntimeInstanceTarget(type(None))]
        return [target for target in found if not is_none(target)]

    # -- bindings ------------------------------------------------------

    def binding(self, binding: scopes.Binding) -> list[Target]:
        """What the name introduced by `binding` refers to."""
        if id(binding.node) in self._active:
            return []  # self-referential assignment such as `x = x`
        self._active.add(id(binding.node))
        try:
            return self._binding_targets(binding)
        finally:
            self._active.discard(id(binding.node))

    def binding_targets(self, bindings: list[scopes.Binding]) -> list[Target]:
        return [target for binding in bindings for target in self.binding(binding)]

    def _binding_targets(self, binding: scopes.Binding) -> list[Target]:
        form, scope = binding.form, binding.owner
        if form == scopes.DEF:
            return [FunctionTarget(binding.node, self)]
        if form == scopes.CLASS:
            return [ClassTarget(binding.node, self)]
        if form == scopes.IMPORT:
            return self.module_target(binding.module)
        if form == scopes.FROM_IMPORT:
            return self.imported_member(binding.module, binding.node.name)
        if form == scopes.PARAM:
            return self._param_targets(binding)
        if binding.annotation is not None or form == scopes.EXCEPT:
            return self.instances([binding.annotation or binding.value], scope)
        return self.expression(binding.value, scope)

    def _param_targets(self, binding: scopes.Binding) -> list[Target]:
        owner = binding.owner
        if binding.name == "self" and owner.parent is not None and owner.parent.kind == "class":
            return [InstanceTarget(owner.parent.node, self)]
        return self.instances([binding.annotation], owner)

    def instances(self, nodes, scope: scopes.Scope) -> list[Target]:
        """Instances of the classes named by type expressions, such as annotations."""
        classes = [target for node in nodes for target in self.expression(node, scope)]
        return [instance for target in classes for instance in target.called()]

    def symbol(self, binding: scopes.Binding) -> Symbol:
        """The completion record for a bound name."""
        simple = _SIMPLE_KINDS.get(binding.form)
        if simple is not None:
            return Symbol.of(binding.name, simple)
        return name_symbol(binding.name, self.binding(binding))

    # -- modules -------------------------------------------------------

    def module_target(self, dotted: str) -> list[Target]:
        handle = self.modules.resolve(dotted)
        return [ModuleTarget(handle, self)] if handle else []

    def imported_member(self, dotted: str, name: str) -> list[Target]:
        """Resolve `from <dotted> import <name>`, which may itself be a module."""
        handle = self.modules.resolve(dotted)
        member = self.member_targets(handle, name) if handle else []
        return member or self.module_target(f"{dotted}.{name}" if dotted else name)

    def member_targets(self, handle, name: str) -> list[Target]:
        if isinstance(handle, RuntimeModule):
            member = getattr(handle.module, name, MISSING)
            return [] if member is MISSING else [RuntimeTarget(member, name)]
        resolver, bindings = self._module_bindings(handle, name)
        return resolver.binding_targets(bindings)

    def member_definitions(self, handle, name: str) -> list[Definition]:
        """Where a module member is defined, for `goto` through a module."""
        if isinstance(handle, RuntimeModule):
            return [target.definition() for target in self.member_targets(handle, name)]
        resolver, bindings = self._module_bindings(handle, name)
        return resolver.binding_definitions(bindings)

    def module_definition(self, handle) -> Definition:
        if isinstance(handle, RuntimeModule):
            return definitions.imported_module(handle.name, handle.module)
        return definitions.module(handle.name, handle.path, definitions.docstring_of(handle.tree))

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

    def _module_bindings(self, handle, name: str):
        resolver, tree = self._sibling(handle)
        return resolver, scopes.live_bindings(tree.root, name, None)

    def _sibling(self, handle):
        """The resolver and scope tree of a project module, built on first use."""
        if handle.name not in self._siblings:
            tree = scopes.build(handle.tree)
            resolver = Resolver(tree, self.modules, handle, self._siblings)
            self._siblings[handle.name] = (resolver, tree)
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
            for binding in _distinct(self.self_bindings(klass)):
                symbols.setdefault(binding.name, self.symbol(binding))
        return list(symbols.values())

    def class_members(self, node: ast.ClassDef, name: str) -> list[scopes.Binding]:
        """Bindings of `name` in the class body, or in that of an in-file base."""
        for klass in self.linearize(node):
            found = scopes.live_bindings(self.tree.scope_for(klass), name, None)
            if found:
                return found
        return []

    def instance_members(self, node: ast.ClassDef, name: str) -> list[scopes.Binding]:
        """Class-level bindings of `name`, or the `self.name = ...` that creates it."""
        for klass in self.linearize(node):
            body = scopes.live_bindings(self.tree.scope_for(klass), name, None)
            found = body or [b for b in self.self_bindings(klass) if b.name == name]
            if found:
                return found
        return []

    def self_bindings(self, klass: ast.ClassDef) -> list[scopes.Binding]:
        """The `self.name = ...` assignments of a class, as bindings of its instances."""
        if id(klass) not in self._attributes:
            self._attributes[id(klass)] = list(self._init_bindings(klass))
        return self._attributes[id(klass)]

    def _init_bindings(self, klass: ast.ClassDef):
        for statement in klass.body:
            if not isinstance(statement, scopes.FUNCTION_NODES) or statement.name != "__init__":
                continue
            scope = self.tree.scope_for(statement)
            for node in ast.walk(statement):
                for target in _assignment_targets(node):
                    if _is_self_attribute(target):
                        yield scopes.Binding(
                            name=target.attr,
                            lineno=target.lineno,
                            form=scopes.ASSIGN,
                            node=target,
                            value=node.value,
                            annotation=getattr(node, "annotation", None),
                            owner=scope,
                        )

    # -- calls ---------------------------------------------------------

    def returned(self, node: ast.AST) -> list[Target]:
        """What calling `node` evaluates to, read off its `return` statements."""
        if id(node) in self._active:
            return []  # directly or mutually recursive function
        self._active.add(id(node))
        try:
            return self._returned(node)
        finally:
            self._active.discard(id(node))

    def _returned(self, node: ast.AST) -> list[Target]:
        scope = self.tree.scope_for(node)
        values = [statement.value for statement in _return_statements(node)]
        returned = [value for value in values if value is not None]
        found = [target for value in returned for target in self.expression(value, scope)]
        if len(returned) < len(values) or not values:
            found.append(RuntimeInstanceTarget(type(None)))
        return found

    # -- definitions ---------------------------------------------------

    def binding_definitions(self, bindings: list[scopes.Binding]) -> list[Definition]:
        return [self.binding_definition(binding) for binding in bindings]

    def binding_definition(self, binding: scopes.Binding) -> Definition:
        """The record `goto` answers with for a bound name."""
        if binding.form == scopes.DEF:
            return self.function_definition(binding.node)
        if binding.form == scopes.CLASS:
            return self.class_definition(binding.node, CLASS)
        return self._record(
            binding.node,
            binding.name,
            self._binding_kind(binding),
            self._binding_full_name(binding),
            self._binding_description(binding),
        )

    def function_definition(self, node: ast.AST) -> Definition:
        return self._record(
            node,
            node.name,
            FUNCTION,
            self._node_full_name(node),
            definitions.function_description(node),
            definitions.docstring_of(node),
        )

    def class_definition(self, node: ast.ClassDef, kind: str) -> Definition:
        """The class itself, or an instance of it when `kind` is `instance`."""
        return self._record(
            node,
            node.name,
            kind,
            self._node_full_name(node),
            describe(kind, node.name, node.name),
            definitions.docstring_of(node),
        )

    def _record(self, node, name, kind, full_name, description, docstring="") -> Definition:
        """A definition for a node of the module this resolver reads."""
        return Definition(
            name=name,
            kind=kind,
            full_name=full_name,
            module_path=self.module.path,
            line=node.lineno,
            column=definitions.name_column(self.module.lines, node, name),
            description=description,
            docstring=docstring,
        )

    def _node_full_name(self, node: ast.AST) -> str:
        return ".".join([self.module.name, *scopes.qualified_prefix(self.tree.scope_for(node))])

    def _binding_full_name(self, binding: scopes.Binding) -> str:
        # An attribute assigned onto `self` belongs to the class, not the method.
        scope = binding.owner.parent if _is_self_attribute(binding.node) else binding.owner
        return ".".join([self.module.name, *scopes.qualified_prefix(scope), binding.name])

    def _binding_kind(self, binding: scopes.Binding) -> str:
        if binding.form == scopes.FROM_IMPORT:
            return name_symbol(binding.name, self.binding(binding)).kind
        return _SIMPLE_KINDS.get(binding.form, STATEMENT)

    def _binding_description(self, binding: scopes.Binding) -> str:
        if binding.form == scopes.ASSIGN and binding.value is not None:
            return ast.unparse(binding.value)
        if binding.form == scopes.PARAM:
            return describe(PARAM, binding.name)
        return self._statement_text(binding.node.lineno)

    def _statement_text(self, lineno: int) -> str:
        lines = self.module.lines
        return lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""


def name_symbol(name: str, found: list[Target]) -> Symbol:
    """Describe `name` given what it was resolved to."""
    if not found:
        return Symbol.of(name, STATEMENT)
    return Symbol.of(name, found[0].kind, found[0].type_name)


#: Binding forms whose completion type never depends on resolution.
_SIMPLE_KINDS = {
    scopes.DEF: FUNCTION,
    scopes.CLASS: CLASS,
    scopes.PARAM: PARAM,
    scopes.IMPORT: MODULE,
}

_NESTED_SCOPES = (*scopes.FUNCTION_NODES, ast.ClassDef, ast.Lambda)


def _builtin_target(name: str) -> list[Target]:
    member = getattr(builtins, name, MISSING)
    return [] if member is MISSING else [RuntimeTarget(member, name)]


def _distinct(bindings: list[scopes.Binding]) -> list[scopes.Binding]:
    """The latest binding for each name, in first-appearance order."""
    latest = {binding.name: binding for binding in bindings}
    return list(latest.values())


def _return_statements(node: ast.AST) -> list[ast.Return]:
    """The `return` statements of `node`, ignoring those of functions nested in it."""
    found = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Return):
            found.append(child)
        elif not isinstance(child, _NESTED_SCOPES):
            found.extend(_return_statements(child))
    return found


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
