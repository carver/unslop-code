"""Static analysis of a parsed module: scopes, bindings and value inference.

These three concerns are mutually recursive - the type of an assignment
depends on name lookup, name lookup depends on the scope tree, and a class
member list depends on both - so they live together.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from . import symbols
from .definitions import Definition, describe, docstring_of, qualified
from .importing import STAR, alias_column, bound_name, imported_module
from .runtime import (
    NONE,
    RuntimeInstance,
    RuntimeValue,
    Union,
    Value,
    builtin_index,
    union,
)
from .source import Source, indent_of
from .symbols import CLASS, FUNCTION, INSTANCE, MODULE, PARAM, STATEMENT, Symbol

FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPE_NODES = FUNCTION_NODES + (ast.ClassDef,)
BRANCHING_NODES = (ast.If, ast.Try, ast.While, ast.For, ast.AsyncFor, ast.Match)

MODULE_SCOPE = "module"
FUNCTION_SCOPE = "function"
CLASS_SCOPE = "class"

MAX_DEPTH = 8


# --------------------------------------------------------------------------
# Scope tree
# --------------------------------------------------------------------------


@dataclass
class Scope:
    """A region of the file that binds names."""

    node: ast.AST
    kind: str
    parent: Optional["Scope"]
    start: int
    end: int
    """Last line of the body as it was parsed."""
    soft_end: int
    """Last line a cursor may still be typing into, past the parsed body."""
    indent: int
    children: List["Scope"] = field(default_factory=list)
    bindings: Optional[List[Symbol]] = None
    index: Optional[Dict[str, Symbol]] = None


def build_scopes(tree: ast.Module, lines: List[str]) -> Scope:
    """Build the scope tree of a module, outermost first."""
    module = Scope(tree, MODULE_SCOPE, None, 1, len(lines), len(lines), -1)
    _add_children(module, lines)
    return module


def _add_children(scope: Scope, lines: List[str]) -> None:
    for node, _ in scope_statements(scope.node):
        if not isinstance(node, SCOPE_NODES):
            continue
        kind = CLASS_SCOPE if isinstance(node, ast.ClassDef) else FUNCTION_SCOPE
        child = Scope(
            node, kind, scope, node.body[0].lineno, node.end_lineno,
            soft_end(node, lines), node.col_offset,
        )
        scope.children.append(child)
        _add_children(child, lines)


def soft_end(node: ast.AST, lines: List[str]) -> int:
    """Last line that a block still being typed into can reach.

    Blank or more deeply indented lines after the final statement belong to
    the block, which is where the cursor sits while code is being added.
    """
    end = node.end_lineno
    while end < len(lines):
        following = lines[end]
        if following.strip() and indent_of(following) <= node.col_offset:
            break
        end += 1
    return end


def scope_statements(node: ast.AST, conditional: bool = False) -> Iterator[Tuple[ast.stmt, bool]]:
    """Statements of ``node``'s own scope, flagged when they may not run.

    Compound statements are flattened; nested definitions are yielded but not
    entered, since they open a scope of their own.
    """
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.stmt, ast.excepthandler)):
            continue
        yield child, conditional
        if not isinstance(child, SCOPE_NODES):
            yield from scope_statements(child, conditional or isinstance(child, BRANCHING_NODES))


def walk_scopes(scope: Scope) -> Iterator[Scope]:
    yield scope
    for child in scope.children:
        yield from walk_scopes(child)


def lookup_chain(scope: Scope) -> Iterator[Scope]:
    """Scopes a name lookup consults, innermost first.

    Class bodies are skipped once left behind: a method does not see the
    attributes of the class it belongs to.
    """
    yield scope
    current = scope.parent
    while current is not None:
        if current.kind != CLASS_SCOPE:
            yield current
        current = current.parent


def innermost_scope(scope: Scope, line: int, indent: int) -> Scope:
    """Deepest scope holding the given position."""
    for child in scope.children:
        if _contains(child, line, indent):
            return innermost_scope(child, line, indent)
    return scope


def _contains(scope: Scope, line: int, indent: int) -> bool:
    if line < scope.start:
        return False
    if line <= scope.end:
        return True
    return line <= scope.soft_end and indent > scope.indent


def prefix_of(scope: Scope) -> str:
    """Dotted names of the definitions enclosing (and including) a scope."""
    names = []
    while scope is not None and scope.kind != MODULE_SCOPE:
        names.append(scope.node.name)
        scope = scope.parent
    return ".".join(reversed(names))


# --------------------------------------------------------------------------
# Bindings that may still be in force
# --------------------------------------------------------------------------


def reachable(group: List[Symbol]) -> List[Symbol]:
    """The bindings of one name a cursor can still see.

    An unconditional binding overwrites whatever came before it; a binding
    inside a branch may not have run, so the previous one survives beside it.
    """
    kept: List[Symbol] = []
    for symbol in reversed(group):
        kept.append(symbol)
        if not symbol.conditional:
            break
    return list(reversed(kept))


def merged(group: List[Symbol]) -> Optional[Symbol]:
    """One symbol standing for every binding a name may currently hold."""
    if not group:
        return None
    if len(group) == 1:
        return group[0]
    return replace(group[-1], value=union([symbol.value for symbol in group]))


# --------------------------------------------------------------------------
# Values backed by the analysed source
# --------------------------------------------------------------------------


class SourceModule(Value):
    """A project module, analysed without importing it."""

    kind = MODULE

    def __init__(self, analyzer: "Analyzer"):
        self.analyzer = analyzer
        self.label = analyzer.module_name

    def bindings(self) -> Dict[str, Symbol]:
        """The names the module body binds, as a cursor at its end sees them."""
        return self.analyzer.latest_bindings(self.analyzer.module_scope)

    def submodules(self) -> List[Symbol]:
        """The modules this module contains, when it is a package."""
        return self.analyzer.project.submodules(self.analyzer.path)

    def members(self):
        """The names the module exports.

        A module with an ``__all__`` exports exactly what it lists; otherwise
        every name it binds, and every module it contains, that does not start
        with an underscore.
        """
        found = {symbol.name: symbol for symbol in self.submodules()}
        found.update(self.bindings())
        exported = exported_names(self.analyzer.tree)
        if exported is None:
            return [symbol for name, symbol in found.items() if not name.startswith("_")]
        return [found.get(name) or Symbol(name) for name in exported]

    def attributes(self, name: str):
        """A module answers for every name it binds, exported or not."""
        found = self.bindings().get(name) or _named(self.submodules(), name)
        return [found] if found is not None else []

    def definitions(self):
        name = self.analyzer.module_name.rpartition(".")[2]
        return [Definition(
            name=name,
            type=MODULE,
            full_name=self.analyzer.module_name,
            module_path=self.analyzer.module_path,
            line=0,
            column=0,
            description=f"module {name}",
            docstring=docstring_of(self.analyzer.tree),
        )]


class SourceClass(Value):
    """A class defined in an analysed file."""

    kind = CLASS

    def __init__(self, analyzer: "Analyzer", node: ast.ClassDef):
        self.analyzer = analyzer
        self.node = node
        self.label = node.name

    def bases(self) -> Iterator["SourceClass"]:
        """Base classes that are defined in the same file."""
        lookup = self.analyzer.lookup_from(self.analyzer.scope_of(self.node).parent)
        for base in self.node.bases:
            symbol = lookup(base.id) if isinstance(base, ast.Name) else None
            if symbol is not None and isinstance(symbol.value, SourceClass):
                yield symbol.value

    def hierarchy(self) -> List["SourceClass"]:
        """This class followed by its bases, most derived first."""
        order, seen, queue = [], set(), [self]
        while queue:
            current = queue.pop(0)
            if current.node in seen:
                continue
            seen.add(current.node)
            order.append(current)
            queue.extend(current.bases())
        return order

    def members(self):
        found: Dict[str, Symbol] = {}
        for klass in self.hierarchy():
            scope = self.analyzer.scope_of(klass.node)
            for name, symbol in self.analyzer.latest_bindings(scope).items():
                found.setdefault(name, symbol)
        return list(found.values())

    def definitions(self):
        return [self.analyzer.definition_at(self.node, CLASS)]


class SourceFunction(Value):
    """A function or method defined in an analysed file."""

    kind = FUNCTION

    def __init__(self, analyzer: "Analyzer", node: ast.AST):
        self.analyzer = analyzer
        self.node = node
        self.label = node.name

    def returns(self, depth: int = 0) -> Optional[Value]:
        """What a call to this function evaluates to.

        Every ``return`` statement of the body contributes a possibility; a
        body that never returns a value evaluates to ``None``. ``depth`` is
        the inference depth of the call, which bounds recursive functions.
        """
        lookup = self.analyzer.lookup_from(self.analyzer.scope_of(self.node))
        returned = [
            statement.value for statement, _ in scope_statements(self.node)
            if isinstance(statement, ast.Return)
        ]
        if not returned:
            return NONE
        return union([
            self.analyzer.resolve(expression, lookup, depth + 1) if expression else NONE
            for expression in returned
        ])

    def definitions(self):
        return [self.analyzer.definition_at(self.node, FUNCTION)]


class SourceInstance(Value):
    """An instance of a class defined in an analysed file."""

    kind = INSTANCE

    def __init__(self, owner: SourceClass):
        self.owner = owner
        self.label = owner.node.name

    def members(self):
        found = {symbol.name: symbol for symbol in self.owner.members()}
        for klass in self.owner.hierarchy():
            for symbol in self.owner.analyzer.self_attributes(klass.node):
                found.setdefault(symbol.name, symbol)
        return list(found.values())

    def definitions(self):
        """The class definition, reported as the instance it produces."""
        return [
            replace(definition, type=INSTANCE, description=f"instance of {definition.name}")
            for definition in self.owner.definitions()
        ]


def instance_of(value: Optional[Value]) -> Optional[Value]:
    """The instance described by a class, or by a type annotation."""
    if isinstance(value, SourceClass):
        return SourceInstance(value)
    if isinstance(value, RuntimeValue) and value.kind == CLASS:
        return RuntimeInstance(value.obj)
    return None


def call_result(value: Optional[Value], depth: int = 0) -> Optional[Value]:
    """The value produced by calling ``value``."""
    if isinstance(value, Union):
        return union([call_result(option, depth) for option in value.options])
    if isinstance(value, SourceFunction):
        return value.returns(depth)
    return instance_of(value)


# --------------------------------------------------------------------------
# Analyzer
# --------------------------------------------------------------------------


class Analyzer:
    """Answers what a file binds, where, and to what."""

    def __init__(self, source: Source, project):
        self.path = source.path
        self.project = project
        self.lines = source.lines
        self.tree = source.tree
        self.module_path, self.module_name, self.package = _location(self.path, project.root)
        self.module_scope = build_scopes(source.tree, source.lines)
        self._scopes = {scope.node: scope for scope in walk_scopes(self.module_scope)}

    # -- scopes ------------------------------------------------------------

    def scope_of(self, node: ast.AST) -> Scope:
        return self._scopes[node]

    def visible(self, line: int, indent: int) -> Dict[str, List[Symbol]]:
        """Bindings reachable at a cursor, the nearest scope winning.

        Local and global bindings only count once the cursor has passed them;
        enclosing scopes are visible in full.
        """
        found: Dict[str, List[Symbol]] = {}
        chain = list(lookup_chain(innermost_scope(self.module_scope, line, indent)))
        for position, scope in enumerate(chain):
            limited = position == 0 or scope is self.module_scope
            for name, group in self.binding_groups(scope, line if limited else None).items():
                found.setdefault(name, group)
        for name, symbol in builtin_index().items():
            found.setdefault(name, [symbol])
        return found

    def lookup_from(self, scope: Scope) -> Callable[[str], Optional[Symbol]]:
        """A name lookup for expressions written inside ``scope``."""

        def lookup(name: str) -> Optional[Symbol]:
            for current in lookup_chain(scope):
                self.bindings(current)
                symbol = current.index.get(name)
                if symbol is not None:
                    return symbol
            return builtin_index().get(name)

        return lookup

    # -- bindings ----------------------------------------------------------

    def bindings(self, scope: Scope) -> List[Symbol]:
        """Every binding made in ``scope``, in source order.

        The result list and its index are published before they are filled,
        so lookups made while inferring a value see the bindings that precede
        it - exactly the names that are in scope at that point.
        """
        if scope.bindings is None:
            scope.bindings, scope.index = [], {}
            qualifier = prefix_of(scope)
            for symbol in self._scope_bindings(scope):
                symbol.origin, symbol.qualifier = self, qualifier
                scope.bindings.append(symbol)
                scope.index[symbol.name] = symbol
        return scope.bindings

    def binding_groups(self, scope: Scope, line: Optional[int] = None) -> Dict[str, List[Symbol]]:
        """Bindings of each name in ``scope`` that may still be in force."""
        groups: Dict[str, List[Symbol]] = {}
        for symbol in self.bindings(scope):
            if line is None or symbol.lineno <= line:
                groups.setdefault(symbol.name, []).append(symbol)
        return {name: reachable(group) for name, group in groups.items()}

    def latest_bindings(self, scope: Scope, line: Optional[int] = None) -> Dict[str, Symbol]:
        """The binding of each name in ``scope`` a cursor would see."""
        return {
            name: merged(group)
            for name, group in self.binding_groups(scope, line).items()
        }

    def _scope_bindings(self, scope: Scope) -> Iterator[Symbol]:
        if scope.kind == FUNCTION_SCOPE:
            yield from self._parameters(scope)
        lookup = self.lookup_from(scope)
        for statement, conditional in scope_statements(scope.node):
            handler = STATEMENT_BINDINGS.get(type(statement))
            if handler is None:
                continue
            for symbol in handler(self, statement, lookup):
                symbol.conditional = conditional
                yield symbol

    def _parameters(self, scope: Scope) -> Iterator[Symbol]:
        """Parameters of a function, including the receiver of a method."""
        arguments = scope.node.args
        declared = arguments.posonlyargs + arguments.args + arguments.kwonlyargs
        declared += [argument for argument in (arguments.vararg, arguments.kwarg) if argument]
        lookup = self.lookup_from(scope)
        values = [self.annotated(argument.annotation, lookup) for argument in declared]
        receiver = self._receiver(scope)
        if receiver is not None and values:
            values[0] = receiver
        for argument, value in zip(declared, values):
            yield Symbol(
                argument.arg, PARAM, argument.lineno, value=value,
                column=argument.col_offset, node=argument,
            )

    def _receiver(self, scope: Scope) -> Optional[Value]:
        """What the first parameter of a method refers to."""
        parent = scope.parent
        if parent is None or parent.kind != CLASS_SCOPE:
            return None
        decorators = {node.id for node in scope.node.decorator_list if isinstance(node, ast.Name)}
        if "staticmethod" in decorators:
            return None
        owner = SourceClass(self, parent.node)
        return owner if "classmethod" in decorators else SourceInstance(owner)

    def self_attributes(self, node: ast.ClassDef) -> List[Symbol]:
        """Attributes a class assigns to ``self`` in its ``__init__``."""
        init = next(
            (child for child in node.body if isinstance(child, FUNCTION_NODES) and child.name == "__init__"),
            None,
        )
        if init is None:
            return []
        lookup = self.lookup_from(self.scope_of(init))
        qualifier = prefix_of(self.scope_of(node))
        found = []
        for statement in ast.walk(init):
            target, value = _self_assignment(statement)
            if target is None:
                continue
            symbol = symbols.from_value(
                target.attr, target.end_lineno, self.resolve(value, lookup),
                column=target.end_col_offset - len(target.attr), node=statement,
            )
            symbol.origin, symbol.qualifier = self, qualifier
            found.append(symbol)
        return found

    # -- definitions -------------------------------------------------------

    def definition_at(self, node: ast.AST, kind: str) -> Definition:
        """The definition record of a `def` or `class` statement in this file."""
        return Definition(
            name=node.name,
            type=kind,
            full_name=qualified(self.module_name, prefix_of(self.scope_of(node).parent), node.name),
            module_path=self.module_path,
            line=node.lineno,
            column=identifier_column(self.lines, node, node.name),
            description=describe(node),
            docstring=docstring_of(node),
        )

    def binding_definition(self, symbol: Symbol) -> Definition:
        """The definition record of a binding made in this file."""
        return Definition(
            name=symbol.name,
            type=symbol.kind,
            full_name=qualified(self.module_name, symbol.qualifier, symbol.name),
            module_path=self.module_path,
            line=symbol.lineno,
            column=symbol.column,
            description=describe(symbol.node),
            docstring=docstring_of(symbol.node),
        )

    # -- inference ---------------------------------------------------------

    def resolve(self, node: Optional[ast.AST], lookup, depth: int = 0) -> Optional[Value]:
        """The value an expression refers to, or ``None`` when unknown."""
        if node is None or depth > MAX_DEPTH:
            return None
        literal = LITERAL_TYPES.get(type(node))
        if literal is not None:
            return RuntimeInstance(literal)
        handler = EXPRESSION_VALUES.get(type(node))
        return handler(self, node, lookup, depth) if handler is not None else None

    def annotated(self, annotation: Optional[ast.AST], lookup) -> Optional[Value]:
        """The value described by a type annotation."""
        return instance_of(self.resolve(annotation, lookup))


def identifier_column(lines: List[str], node: ast.AST, name: str) -> int:
    """Column of the identifier a statement defines, not of its keyword."""
    text = lines[node.lineno - 1]
    found = text.find(name, node.col_offset)
    return found if found >= 0 else node.col_offset


def _location(path: Path, root: Path) -> Tuple[str, str, str]:
    """The path, dotted name and package of a module, relative to the root.

    Paths are written the POSIX way whatever the host separator is, and a file
    outside the root keeps its own path, which no dotted name can reach.
    """
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return path.as_posix(), path.stem, ""
    parts = _name_parts(path, relative)
    package = parts if _is_package(path) else parts[:-1]
    return relative.as_posix(), ".".join(parts), ".".join(package)


def _name_parts(path: Path, relative: Path) -> List[str]:
    """The dotted name of a module, as the parts of its path below the root."""
    if path.is_dir():
        return list(relative.parts)
    parts = list(relative.with_suffix("").parts)
    return parts[:-1] if parts[-1:] == ["__init__"] else parts


def _is_package(path: Path) -> bool:
    """Whether a file is the body of a package rather than a plain module."""
    return path.is_dir() or path.name == "__init__.py"


def exported_names(tree: ast.Module) -> Optional[List[str]]:
    """The names a module's ``__all__`` lists, or ``None`` when it has none."""
    for statement in tree.body:
        if not _assigns_all(statement):
            continue
        listed = statement.value.elts if isinstance(statement.value, (ast.List, ast.Tuple)) else []
        return [
            element.value for element in listed
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    return None


def _assigns_all(statement: ast.stmt) -> bool:
    return isinstance(statement, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "__all__" for target in statement.targets
    )


def _named(group: List[Symbol], name: str) -> Optional[Symbol]:
    """The symbol of ``group`` carrying ``name``."""
    return next((symbol for symbol in group if symbol.name == name), None)


def definitions_of(symbol: Symbol) -> List[Definition]:
    """Where a binding was made, as reported by `goto`.

    Bindings written in an analysed file are reported at their own position;
    names that only exist at runtime fall back to what their value knows.
    """
    if symbol.node is None or symbol.origin is None:
        return symbol.value.definitions() if symbol.value is not None else []
    return [symbol.origin.binding_definition(symbol)]


# --------------------------------------------------------------------------
# Statement bindings
# --------------------------------------------------------------------------


def _targets(target: ast.AST, value: Optional[Value], node: ast.stmt) -> Iterator[Symbol]:
    """Names bound by an assignment target; attribute targets bind nothing."""
    if isinstance(target, ast.Name):
        yield symbols.from_value(
            target.id, target.lineno, value, column=target.col_offset, node=node,
        )
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _targets(element, None, node)


def _self_assignment(statement: ast.AST):
    """Target and value of a ``self.name = ...`` statement, or ``(None, None)``."""
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target, value = statement.targets[0], statement.value
    elif isinstance(statement, ast.AnnAssign):
        target, value = statement.target, statement.value
    else:
        return None, None
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    ):
        return target, value
    return None, None


def _function_bindings(analyzer, node, lookup):
    yield Symbol(
        node.name, FUNCTION, node.lineno, value=SourceFunction(analyzer, node),
        column=identifier_column(analyzer.lines, node, node.name), node=node,
    )


def _class_bindings(analyzer, node, lookup):
    yield Symbol(
        node.name, CLASS, node.lineno, value=SourceClass(analyzer, node),
        column=identifier_column(analyzer.lines, node, node.name), node=node,
    )


def _assign_bindings(analyzer, node, lookup):
    value = analyzer.resolve(node.value, lookup)
    for target in node.targets:
        yield from _targets(target, value, node)


def _ann_assign_bindings(analyzer, node, lookup):
    value = analyzer.resolve(node.value, lookup) if node.value else analyzer.annotated(node.annotation, lookup)
    yield from _targets(node.target, value, node)


def _aug_assign_bindings(analyzer, node, lookup):
    yield from _targets(node.target, None, node)


def _for_bindings(analyzer, node, lookup):
    yield from _targets(node.target, None, node)


def _with_bindings(analyzer, node, lookup):
    for item in node.items:
        if item.optional_vars is not None:
            yield from _targets(item.optional_vars, None, node)


def _except_bindings(analyzer, node, lookup):
    if node.name:
        yield Symbol(node.name, STATEMENT, node.lineno, column=node.col_offset, node=node)


def _import_bindings(analyzer, node, lookup):
    for alias in node.names:
        yield Symbol(
            bound_name(alias), MODULE, node.lineno,
            value=analyzer.project.module(imported_module(alias)),
            column=alias_column(alias), node=node,
        )


def _import_from_bindings(analyzer, node, lookup):
    """`from X import a, b` binds what `X` calls those names; `*` binds all of them."""
    module = analyzer.project.module_for(analyzer, node.level, node.module or "")
    for alias in node.names:
        if alias.name != STAR:
            value = module.attribute(alias.name) if module is not None else None
            yield symbols.from_value(
                alias.asname or alias.name, node.lineno, value,
                column=alias_column(alias), node=node,
            )
        elif module is not None:
            for symbol in module.members():
                yield replace(symbol, lineno=node.lineno, column=node.col_offset, node=node)


STATEMENT_BINDINGS = {
    ast.FunctionDef: _function_bindings,
    ast.AsyncFunctionDef: _function_bindings,
    ast.ClassDef: _class_bindings,
    ast.Assign: _assign_bindings,
    ast.AnnAssign: _ann_assign_bindings,
    ast.AugAssign: _aug_assign_bindings,
    ast.For: _for_bindings,
    ast.AsyncFor: _for_bindings,
    ast.With: _with_bindings,
    ast.AsyncWith: _with_bindings,
    ast.ExceptHandler: _except_bindings,
    ast.Import: _import_bindings,
    ast.ImportFrom: _import_from_bindings,
}


# --------------------------------------------------------------------------
# Expression values
# --------------------------------------------------------------------------


def _name_value(analyzer, node, lookup, depth):
    symbol = lookup(node.id)
    return symbol.value if symbol is not None else None


def _attribute_value(analyzer, node, lookup, depth):
    owner = analyzer.resolve(node.value, lookup, depth + 1)
    return owner.attribute(node.attr) if owner is not None else None


def _call_value(analyzer, node, lookup, depth):
    return call_result(analyzer.resolve(node.func, lookup, depth + 1), depth + 1)


def _constant_value(analyzer, node, lookup, depth):
    return RuntimeValue(node.value)


def _conditional_value(analyzer, node, lookup, depth):
    """Both arms of ``a if test else b`` remain possible."""
    return union([
        analyzer.resolve(node.body, lookup, depth + 1),
        analyzer.resolve(node.orelse, lookup, depth + 1),
    ])


EXPRESSION_VALUES = {
    ast.Name: _name_value,
    ast.Attribute: _attribute_value,
    ast.Call: _call_value,
    ast.Constant: _constant_value,
    ast.IfExp: _conditional_value,
}

LITERAL_TYPES = {
    ast.List: list,
    ast.ListComp: list,
    ast.Dict: dict,
    ast.DictComp: dict,
    ast.Set: set,
    ast.SetComp: set,
    ast.Tuple: tuple,
    ast.JoinedStr: str,
}
