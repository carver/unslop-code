"""The static scope tree of a module and the bindings each scope introduces."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace

FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

#: How a name came to be bound, which decides how it is typed and described.
DEF = "def"
CLASS = "class"
IMPORT = "import"
FROM_IMPORT = "from"
PARAM = "param"
ASSIGN = "assign"
EXCEPT = "except"
TARGET = "target"


@dataclass(frozen=True)
class Binding:
    """One name introduced into a scope at a particular line."""

    name: str
    lineno: int
    form: str
    node: ast.AST | None = None
    value: ast.expr | None = None
    module: str | None = None
    annotation: ast.expr | None = None
    #: The scope that introduced the name, needed to resolve `value` later.
    owner: "Scope | None" = field(default=None, compare=False, repr=False)


@dataclass
class Scope:
    """A namespace: the module, a function body, or a class body."""

    node: ast.AST
    kind: str  # module | function | class
    parent: "Scope | None" = None
    children: list["Scope"] = field(default_factory=list)
    bindings: list[Binding] = field(default_factory=list)
    star_imports: list[tuple[int, str]] = field(default_factory=list)

    def bind(self, binding: Binding) -> None:
        self.bindings.append(replace(binding, owner=self))


@dataclass
class ScopeTree:
    """The module's scopes, indexed for lookup by AST node and by class name."""

    root: Scope
    by_node: dict[int, Scope]
    classes: dict[str, ast.ClassDef]

    def scope_for(self, node: ast.AST) -> Scope | None:
        return self.by_node.get(id(node))


def build(tree: ast.Module) -> ScopeTree:
    """Build the scope tree for an already-parsed module."""
    builder = _Builder()
    root = builder.enter(tree, "module", None)
    return ScopeTree(root, builder.by_node, builder.classes)


def scope_at(tree: ScopeTree, line: int, indent: int) -> Scope:
    """The innermost scope holding the cursor.

    A cursor on a trailing blank line sits past the last statement of the block
    it belongs to, so a scope that ended just above still claims the cursor when
    the cursor is indented further than the scope's own header.
    """
    scope = tree.root
    while True:
        deeper = [child for child in scope.children if _claims(child, line, indent)]
        if not deeper:
            return scope
        scope = max(deeper, key=lambda child: child.node.lineno)


def _claims(scope: Scope, line: int, indent: int) -> bool:
    node = scope.node
    if node.lineno > line:
        return False
    return line <= (node.end_lineno or node.lineno) or indent > node.col_offset


def lookup_chain(scope: Scope):
    """The scopes searched for a bare name, nearest first (LEGB, minus builtins).

    Class bodies are skipped once we have left them: they are not part of the
    lookup chain of the functions defined inside them.
    """
    yield scope
    current = scope.parent
    while current is not None:
        if current.kind != "class":
            yield current
        current = current.parent


def visible_bindings(scope: Scope, line: int) -> dict[str, Binding]:
    """Bindings reachable from `scope`, nearest scope and latest binding winning.

    The local and global scopes only contribute names bound at or before `line`;
    enclosing function scopes contribute everything, since a closure body runs
    after its enclosing function has finished binding.
    """
    visible: dict[str, Binding] = {}
    for current in lookup_chain(scope):
        limit = line if current.kind == "module" or current is scope else None
        local: dict[str, Binding] = {}
        for binding in current.bindings:
            if limit is None or binding.lineno <= limit:
                local[binding.name] = binding
        for name, binding in local.items():
            visible.setdefault(name, binding)
    return visible


def visible_star_imports(scope: Scope, line: int) -> list[str]:
    """Modules star-imported into the chain, nearest scope first."""
    modules = []
    for current in lookup_chain(scope):
        limit = line if current.kind == "module" or current is scope else None
        modules.extend(
            module for lineno, module in current.star_imports if limit is None or lineno <= limit
        )
    return modules


class _Builder:
    """Walks a module, creating scopes and recording the names they bind."""

    def __init__(self) -> None:
        self.by_node: dict[int, Scope] = {}
        self.classes: dict[str, ast.ClassDef] = {}

    def enter(self, node: ast.AST, kind: str, parent: Scope | None) -> Scope:
        scope = self.open(node, kind, parent)
        self.walk_body(node, scope)
        return scope

    def open(self, node: ast.AST, kind: str, parent: Scope | None) -> Scope:
        scope = Scope(node=node, kind=kind, parent=parent)
        self.by_node[id(node)] = scope
        if parent is not None:
            parent.children.append(scope)
        return scope

    def walk_body(self, node: ast.AST, scope: Scope) -> None:
        for child in node.body:
            self.collect(child, scope)

    def collect(self, node: ast.AST, scope: Scope) -> None:
        handler = _HANDLERS.get(type(node))
        if handler is not None:
            handler(self, node, scope)
            return
        for child in ast.iter_child_nodes(node):
            self.collect(child, scope)

    # -- binding forms -------------------------------------------------

    def function(self, node: ast.AST, scope: Scope) -> None:
        scope.bind(Binding(node.name, node.lineno, DEF, node))
        inner = self.open(node, "function", scope)
        # Parameters bind before the body, so a body assignment overrides them.
        for arg in _arguments(node.args):
            inner.bind(Binding(arg.arg, node.lineno, PARAM, arg, annotation=arg.annotation))
        self.walk_body(node, inner)

    def class_def(self, node: ast.ClassDef, scope: Scope) -> None:
        scope.bind(Binding(node.name, node.lineno, CLASS, node))
        self.classes.setdefault(node.name, node)
        self.enter(node, "class", scope)

    def import_stmt(self, node: ast.Import, scope: Scope) -> None:
        for alias in node.names:
            # `import a.b` binds the root package `a`; `import a.b as c` binds `c`.
            name = alias.asname or alias.name.split(".")[0]
            target = alias.name if alias.asname else name
            scope.bind(Binding(name, node.lineno, IMPORT, alias, module=target))

    def import_from(self, node: ast.ImportFrom, scope: Scope) -> None:
        module = node.module or ""
        for alias in node.names:
            if alias.name == "*":
                scope.star_imports.append((node.lineno, module))
                continue
            scope.bind(
                Binding(alias.asname or alias.name, node.lineno, FROM_IMPORT, alias, module=module)
            )

    def assign(self, node: ast.Assign, scope: Scope) -> None:
        for target in node.targets:
            self.targets(target, scope, node.lineno, node.value)

    def ann_assign(self, node: ast.AnnAssign, scope: Scope) -> None:
        self.targets(node.target, scope, node.lineno, node.value, node.annotation)

    def aug_assign(self, node: ast.AugAssign, scope: Scope) -> None:
        self.targets(node.target, scope, node.lineno, None)

    def named_expr(self, node: ast.NamedExpr, scope: Scope) -> None:
        self.targets(node.target, scope, node.lineno, node.value)
        self.collect(node.value, scope)

    def for_loop(self, node: ast.AST, scope: Scope) -> None:
        self.targets(node.target, scope, node.lineno, None)
        for child in node.body + node.orelse + [node.iter]:
            self.collect(child, scope)

    def with_stmt(self, node: ast.AST, scope: Scope) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self.targets(item.optional_vars, scope, node.lineno, None)
            self.collect(item.context_expr, scope)
        for child in node.body:
            self.collect(child, scope)

    def handler(self, node: ast.ExceptHandler, scope: Scope) -> None:
        if node.name:
            scope.bind(Binding(node.name, node.lineno, EXCEPT, node, value=node.type))
        for child in node.body:
            self.collect(child, scope)

    def targets(self, target, scope, lineno, value, annotation=None) -> None:
        """Bind every `Name` in an assignment target, descending through unpacking."""
        if isinstance(target, ast.Name):
            form = ASSIGN if value is not None or annotation is not None else TARGET
            scope.bind(Binding(target.id, lineno, form, target, value, annotation=annotation))
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self.targets(element, scope, lineno, None)


def _arguments(args: ast.arguments):
    """Every parameter of a signature, in declaration order."""
    optional = [args.vararg, args.kwarg]
    return [*args.posonlyargs, *args.args, *args.kwonlyargs, *[a for a in optional if a]]


_HANDLERS = {
    ast.FunctionDef: _Builder.function,
    ast.AsyncFunctionDef: _Builder.function,
    ast.ClassDef: _Builder.class_def,
    ast.Import: _Builder.import_stmt,
    ast.ImportFrom: _Builder.import_from,
    ast.Assign: _Builder.assign,
    ast.AnnAssign: _Builder.ann_assign,
    ast.AugAssign: _Builder.aug_assign,
    ast.NamedExpr: _Builder.named_expr,
    ast.For: _Builder.for_loop,
    ast.AsyncFor: _Builder.for_loop,
    ast.With: _Builder.with_stmt,
    ast.AsyncWith: _Builder.with_stmt,
    ast.ExceptHandler: _Builder.handler,
}
