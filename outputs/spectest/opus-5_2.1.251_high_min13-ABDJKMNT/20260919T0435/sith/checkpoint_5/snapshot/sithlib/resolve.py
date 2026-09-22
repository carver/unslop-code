"""Resolving names and expressions to the things they refer to.

A name can denote several things at once -- two branches of an `if` may bind it
differently -- so every resolution step yields a list of targets rather than a
single one.  What the targets themselves can do lives in `targets.py`.
"""

from __future__ import annotations

import ast
import builtins

from . import callsites, definitions, flow, imports, params, scopes, stubs
from .definitions import Definition
from .modules import RuntimeModule
from .symbols import CLASS, FUNCTION, INSTANCE, MODULE, PARAM, STATEMENT, Symbol, describe
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
    built for other project files have no position of their own.  `follow` is
    the `--follow-imports` setting, which every module of the request shares.
    """

    def __init__(self, tree, modules, module, siblings=None, position=None, follow=False,
                 stubbed=True) -> None:
        self.tree = tree
        self.modules = modules
        self.module = module
        self.position = position
        self.follow = follow
        self._siblings = {} if siblings is None else siblings
        #: The module's stub, read on first use; a stub has no stub of its own.
        self._stub = MISSING if stubbed else None
        self._active: set[int] = set()
        self._following: set[int] = set()
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
        """What a bare name refers to: a binding, a star import, or a builtin."""
        bindings = self.bindings_for(name, scope)
        if bindings:
            return self.narrowed(name, scope, self.binding_targets(bindings))
        found = self._starred(name, scope) or self.stub_members(name) or _builtin_target(name)
        return self.narrowed(name, scope, found)

    def _starred(self, name: str, scope: scopes.Scope) -> list[Target]:
        """A name that a `from ... import *` in the scope chain makes visible."""
        for module, level in scopes.visible_star_imports(scope, self.position):
            handle = self.module_handle(module, level)
            exported = handle and any(s.name == name for s in self.module_exports(handle))
            if exported:
                return self.member_targets(handle, name)
        return []

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
            return self.imported_member(binding)
        if form == scopes.PARAM:
            return self._param_targets(binding)
        stubbed = self.stub_annotated(binding)
        if stubbed:
            return stubbed
        if binding.annotation is not None or form == scopes.EXCEPT:
            return self.instances([binding.annotation or binding.value], scope)
        return self.expression(binding.value, scope)

    def _param_targets(self, binding: scopes.Binding) -> list[Target]:
        """A parameter's type: its annotation, its stub, or how it is called."""
        owner = binding.owner
        if binding.name == "self" and owner.parent is not None and owner.parent.kind == "class":
            return [InstanceTarget(owner.parent.node, self)]
        if binding.annotation is not None:
            return self.instances([binding.annotation], owner)
        declared = self.stub_declarations(owner.node)
        annotations = [params.annotation(node.args, binding.name) for node in declared]
        if any(annotations):
            return self.stub.instances([node for node in annotations if node])
        return callsites.parameter_types(self, owner.node, binding.name)

    def instances(self, nodes, scope: scopes.Scope) -> list[Target]:
        """Instances of the classes named by type expressions, such as annotations.

        An expression that already denotes an instance -- `None` written as an
        annotation -- stands for itself rather than for something to call.
        """
        classes = [target for node in nodes for target in self.expression(node, scope)]
        return [instance for target in classes for instance in target.called() or _itself(target)]

    def symbol(self, binding: scopes.Binding) -> Symbol:
        """The completion record for a bound name."""
        simple = _SIMPLE_KINDS.get(binding.form)
        if simple is not None:
            return Symbol.of(binding.name, simple)
        return name_symbol(binding.name, self.binding(binding))

    # -- modules -------------------------------------------------------

    def module_handle(self, dotted: str, level: int = 0):
        """The module an import names, with relative levels already applied."""
        name = imports.absolute(self.module, level, dotted)
        return self.modules.resolve(name) if name is not None else None

    def module_target(self, dotted: str, level: int = 0) -> list[Target]:
        handle = self.module_handle(dotted, level)
        return [ModuleTarget(handle, self)] if handle else []

    def imported_member(self, binding: scopes.Binding) -> list[Target]:
        """Resolve `from <module> import <name>`, which may itself be a submodule."""
        dotted = imports.absolute(self.module, binding.level, binding.module)
        if dotted is None:
            return []
        handle = self.modules.resolve(dotted)
        if handle is None:
            return self.module_target(imports.submodule(dotted, binding.node.name))
        return self.member_targets(handle, binding.node.name)

    def member_targets(self, handle, name: str) -> list[Target]:
        if isinstance(handle, RuntimeModule):
            member = getattr(handle.module, name, MISSING)
            return [] if member is MISSING else [RuntimeTarget(member, name)]
        resolver, bindings = self.module_bindings(handle, name)
        return (
            resolver.binding_targets(bindings)
            or resolver.stub_members(name)
            or self.module_target(imports.submodule(handle.name, name))
        )

    def member_definitions(self, handle, name: str) -> list[Definition]:
        """Where a module member is defined, for `goto` through a module."""
        if isinstance(handle, RuntimeModule):
            return [target.definition() for target in self.member_targets(handle, name)]
        resolver, bindings = self.module_bindings(handle, name)
        if bindings:
            return resolver.binding_definitions(bindings)
        stubbed = resolver.stub_member_definitions(name)
        if stubbed:
            return stubbed
        found = self.modules.resolve(imports.submodule(handle.name, name))
        return [self.module_definition(found)] if found else []

    def module_definition(self, handle) -> Definition:
        if isinstance(handle, RuntimeModule):
            return definitions.imported_module(handle.name, handle.module)
        return definitions.module(handle.name, handle.path, definitions.docstring_of(handle.tree))

    def module_symbols(self, handle) -> list[Symbol]:
        """The attributes a module offers: its public names and its submodules."""
        return _public(self._module_names(handle))

    def module_exports(self, handle) -> list[Symbol]:
        """The names a module hands to `import *` and to import completion.

        `__all__` says exactly which names those are, underscores included;
        without it, every name that does not start with an underscore is sent.
        """
        offered = self._module_names(handle)
        exported = handle.exports
        if exported is None:
            return _public(offered)
        return [offered.get(name, Symbol.of(name, STATEMENT)) for name in exported]

    def _module_names(self, handle) -> dict[str, Symbol]:
        """Every top-level name of a module, with a package's submodules added."""
        offered = self._bound_names(handle)
        for name in handle.submodules():
            offered.setdefault(name, Symbol.of(name, MODULE))
        return offered

    def _bound_names(self, handle) -> dict[str, Symbol]:
        if isinstance(handle, RuntimeModule):
            module = handle.module
            return {name: Symbol.from_object(name, getattr(module, name, None))
                    for name in dir(module)}
        resolver, tree = self.sibling(handle)
        offered = {binding.name: resolver.symbol(binding)
                   for binding in _distinct(tree.root.bindings)}
        for name, symbol in resolver.stub_symbols().items():
            offered.setdefault(name, symbol)
        return offered

    def module_bindings(self, handle, name: str):
        """The resolver of a project module, and what it binds `name` to."""
        resolver, tree = self.sibling(handle)
        return resolver, scopes.live_bindings(tree.root, name, None)

    def sibling(self, handle):
        """The resolver and scope tree of another project module."""
        return for_module(handle, self.modules, self._siblings, self.follow)

    # -- stubs ---------------------------------------------------------

    @property
    def stub(self) -> stubs.Stub | None:
        """The `.pyi` describing this module, parsed on first use."""
        if self._stub is MISSING:
            self._stub = self._read_stub()
        return self._stub

    def _read_stub(self) -> stubs.Stub | None:
        handle = self.modules.stub_for(self.module.name)
        if handle is None:
            return None
        tree = scopes.build(handle.tree)
        resolver = Resolver(tree, self.modules, handle, follow=self.follow, stubbed=False)
        return stubs.Stub(handle, tree, resolver)

    def stub_declarations(self, node: ast.AST) -> list[ast.AST]:
        """The stub's `def`s for a function of this module, overloads included."""
        if self.stub is None:
            return []
        owners = self._owners(node)
        return self.stub.functions(owners[:-1], node.name)

    def stub_members(self, name: str, node: ast.ClassDef | None = None) -> list[Target]:
        """What a stub declares under `name`, at module level or inside a class."""
        return self.stub.targets(self._owners(node), name) if self.stub else []

    def stub_member_definitions(self, name: str, node: ast.ClassDef | None = None):
        """Where a stub declares `name`, for a definition the source does not have."""
        return self.stub.definitions(self._owners(node), name) if self.stub else []

    def stub_symbols(self, node: ast.ClassDef | None = None) -> dict[str, Symbol]:
        """The names a stub declares, for completion."""
        return self.stub.symbols(self._owners(node)) if self.stub else {}

    def stub_annotated(self, binding: scopes.Binding) -> list[Target]:
        """The type a stub gives a bound name, which outranks what the code says."""
        if self.stub is None or binding.owner is None:
            return []
        # An attribute assigned onto `self` is declared by the class, not the method.
        scope = binding.owner.parent if _is_self_attribute(binding.node) else binding.owner
        return self.stub.annotated(scopes.qualified_prefix(scope), binding.name)

    def _owners(self, node: ast.AST | None) -> list[str]:
        """The classes and functions enclosing a node, naming it as a stub would."""
        return scopes.qualified_prefix(self.tree.scope_for(node)) if node is not None else []

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
            for name, symbol in self.stub_symbols(klass).items():
                symbols.setdefault(name, symbol)
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
        annotated = [d.returns for d in self.stub_declarations(node) if d.returns is not None]
        if annotated:
            return self.stub.instances(annotated)
        scope = self.tree.scope_for(node)
        values = [statement.value for statement in _return_statements(node)]
        returned = [value for value in values if value is not None]
        found = [target for value in returned for target in self.expression(value, scope)]
        if len(returned) < len(values) or not values:
            found.append(RuntimeInstanceTarget(type(None)))
        return found

    # -- definitions ---------------------------------------------------

    def binding_definitions(self, bindings: list[scopes.Binding]) -> list[Definition]:
        return [record for binding in bindings for record in self._definitions(binding)]

    def _definitions(self, binding: scopes.Binding) -> list[Definition]:
        """Where a binding leads, following imports when the request asked for it.

        An import chain that leaves the project, or loops back on itself, ends
        at the import statement that was being followed.
        """
        if not self.follow or binding.form not in imports.FORMS:
            return [self.binding_definition(binding)]
        if id(binding.node) in self._following:
            return [self.binding_definition(binding)]
        self._following.add(id(binding.node))
        try:
            return imports.followed(self, binding) or [self.binding_definition(binding)]
        finally:
            self._following.discard(id(binding.node))

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


def for_module(handle, modules, siblings: dict, follow: bool = False):
    """The resolver and scope tree of a project module, built on first use."""
    if handle.name not in siblings:
        tree = scopes.build(handle.tree)
        siblings[handle.name] = (Resolver(tree, modules, handle, siblings, follow=follow), tree)
    return siblings[handle.name]


def _itself(target: Target) -> list[Target]:
    """A type expression that already denotes an instance, such as `None`."""
    return [target] if target.kind == INSTANCE else []


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


def _public(symbols: dict[str, Symbol]) -> list[Symbol]:
    """The symbols whose names do not start with an underscore."""
    return [symbol for name, symbol in symbols.items() if not name.startswith("_")]


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
