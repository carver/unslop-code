"""Static analysis of a parsed module: scopes, bindings and value inference.

These three concerns are mutually recursive - the type of an assignment
depends on name lookup, name lookup depends on the scope tree, and a class
member list depends on both - so they live together.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

from . import symbols
from .runtime import RuntimeInstance, RuntimeValue, Value, builtin_index, import_module
from .source import Source, indent_of
from .symbols import CLASS, FUNCTION, INSTANCE, MODULE, PARAM, STATEMENT, Symbol

FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPE_NODES = FUNCTION_NODES + (ast.ClassDef,)

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
    for node in inner_statements(scope.node):
        if not isinstance(node, SCOPE_NODES):
            continue
        kind = CLASS_SCOPE if isinstance(node, ast.ClassDef) else FUNCTION_SCOPE
        child = Scope(
            node, kind, scope, node.body[0].lineno, node.end_lineno,
            _soft_end(node, lines), node.col_offset,
        )
        scope.children.append(child)
        _add_children(child, lines)


def _soft_end(node: ast.AST, lines: List[str]) -> int:
    """Last line that a body still being typed into can reach.

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


def inner_statements(node: ast.AST) -> Iterator[ast.stmt]:
    """Statements of ``node``'s own scope.

    Compound statements are flattened; nested definitions are yielded but not
    entered, since they open a scope of their own.
    """
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.stmt, ast.excepthandler)):
            continue
        yield child
        if not isinstance(child, SCOPE_NODES):
            yield from inner_statements(child)


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


# --------------------------------------------------------------------------
# Values backed by the analysed source
# --------------------------------------------------------------------------


class SourceModule(Value):
    """A project module, analysed without importing it."""

    kind = MODULE

    def __init__(self, analyzer: "Analyzer"):
        self.analyzer = analyzer

    def members(self):
        bindings = self.analyzer.latest_bindings(self.analyzer.module_scope)
        return [symbol for symbol in bindings.values() if not symbol.name.startswith("_")]


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


def instance_of(value: Optional[Value]) -> Optional[Value]:
    """The value produced by calling ``value``, when it names a known class."""
    if isinstance(value, SourceClass):
        return SourceInstance(value)
    if isinstance(value, RuntimeValue) and value.kind == CLASS:
        return RuntimeInstance(value.obj)
    return None


# --------------------------------------------------------------------------
# Analyzer
# --------------------------------------------------------------------------


class Analyzer:
    """Answers what a file binds, where, and to what."""

    def __init__(self, source: Source):
        self.path = source.path
        self.module_scope = build_scopes(source.tree, source.lines)
        self._scopes = {scope.node: scope for scope in walk_scopes(self.module_scope)}
        self._modules: Dict[Path, SourceModule] = {}

    # -- scopes ------------------------------------------------------------

    def scope_of(self, node: ast.AST) -> Scope:
        return self._scopes[node]

    def visible(self, line: int, indent: int) -> Dict[str, Symbol]:
        """Symbols reachable at a cursor, nearest binding winning.

        Local and global bindings only count once the cursor has passed them;
        enclosing scopes are visible in full.
        """
        found: Dict[str, Symbol] = {}
        chain = list(lookup_chain(innermost_scope(self.module_scope, line, indent)))
        for position, scope in enumerate(chain):
            limited = position == 0 or scope is self.module_scope
            for name, symbol in self.latest_bindings(scope, line if limited else None).items():
                found.setdefault(name, symbol)
        for name, symbol in builtin_index().items():
            found.setdefault(name, symbol)
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
            for symbol in self._scope_bindings(scope):
                scope.bindings.append(symbol)
                scope.index[symbol.name] = symbol
        return scope.bindings

    def latest_bindings(self, scope: Scope, line: Optional[int] = None) -> Dict[str, Symbol]:
        """Last binding of each name in ``scope``, optionally up to ``line``."""
        latest: Dict[str, Symbol] = {}
        for symbol in self.bindings(scope):
            if line is None or symbol.lineno <= line:
                latest[symbol.name] = symbol
        return latest

    def _scope_bindings(self, scope: Scope) -> Iterator[Symbol]:
        if scope.kind == FUNCTION_SCOPE:
            yield from self._parameters(scope)
        lookup = self.lookup_from(scope)
        for statement in inner_statements(scope.node):
            handler = STATEMENT_BINDINGS.get(type(statement))
            if handler is not None:
                yield from handler(self, statement, lookup)

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
            yield Symbol(argument.arg, PARAM, scope.node.lineno, value=value)

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
        found = []
        for statement in ast.walk(init):
            name, value = _self_assignment(statement)
            if name is not None:
                found.append(symbols.from_value(name, statement.lineno, self.resolve(value, lookup)))
        return found

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

    def module_value(self, dotted: str) -> Optional[Value]:
        """Resolve an imported module, preferring a file beside the source."""
        local = self.path.parent.joinpath(*dotted.split(".")).with_suffix(".py")
        if local.is_file():
            return self.local_module(local)
        module = import_module(dotted)
        return RuntimeValue(module) if module is not None else None

    def local_module(self, path: Path) -> SourceModule:
        """Analyse a project file instead of importing it."""
        if path not in self._modules:
            self._modules[path] = SourceModule(Analyzer(Source.load(path)))
        return self._modules[path]


# --------------------------------------------------------------------------
# Statement bindings
# --------------------------------------------------------------------------


def _targets(target: ast.AST, lineno: int, value: Optional[Value]) -> Iterator[Symbol]:
    """Names bound by an assignment target; attribute targets bind nothing."""
    if isinstance(target, ast.Name):
        yield symbols.from_value(target.id, lineno, value)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _targets(element, lineno, None)


def _self_assignment(statement: ast.AST):
    """Name and value of a ``self.name = ...`` statement, or ``(None, None)``."""
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
        return target.attr, value
    return None, None


def _function_bindings(analyzer, node, lookup):
    yield Symbol(node.name, FUNCTION, node.lineno)


def _class_bindings(analyzer, node, lookup):
    yield Symbol(node.name, CLASS, node.lineno, value=SourceClass(analyzer, node))


def _assign_bindings(analyzer, node, lookup):
    value = analyzer.resolve(node.value, lookup)
    for target in node.targets:
        yield from _targets(target, node.lineno, value)


def _ann_assign_bindings(analyzer, node, lookup):
    value = analyzer.resolve(node.value, lookup) if node.value else analyzer.annotated(node.annotation, lookup)
    yield from _targets(node.target, node.lineno, value)


def _aug_assign_bindings(analyzer, node, lookup):
    yield from _targets(node.target, node.lineno, None)


def _for_bindings(analyzer, node, lookup):
    yield from _targets(node.target, node.lineno, None)


def _with_bindings(analyzer, node, lookup):
    for item in node.items:
        if item.optional_vars is not None:
            yield from _targets(item.optional_vars, node.lineno, None)


def _except_bindings(analyzer, node, lookup):
    if node.name:
        yield Symbol(node.name, STATEMENT, node.lineno)


def _import_bindings(analyzer, node, lookup):
    for alias in node.names:
        dotted = alias.name if alias.asname else alias.name.split(".")[0]
        yield Symbol(alias.asname or dotted, MODULE, node.lineno, value=analyzer.module_value(dotted))


def _import_from_bindings(analyzer, node, lookup):
    module = analyzer.module_value(node.module) if node.module and not node.level else None
    for alias in node.names:
        if alias.name != "*":
            value = module.attribute(alias.name) if module is not None else None
            yield symbols.from_value(alias.asname or alias.name, node.lineno, value)
        elif module is not None:
            for symbol in module.members():
                yield replace(symbol, lineno=node.lineno)


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
    return instance_of(analyzer.resolve(node.func, lookup, depth + 1))


def _constant_value(analyzer, node, lookup, depth):
    return RuntimeValue(node.value)


EXPRESSION_VALUES = {
    ast.Name: _name_value,
    ast.Attribute: _attribute_value,
    ast.Call: _call_value,
    ast.Constant: _constant_value,
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
