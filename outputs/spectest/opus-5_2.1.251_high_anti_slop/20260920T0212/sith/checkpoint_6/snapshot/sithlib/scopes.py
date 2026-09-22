"""Lexical scopes: which names are bound where, and which ones a cursor sees."""

import ast

from .bindings import ASSIGN, CLASS, EXCEPT, FUNCTION, IMPORT, PARAM, TARGET
from .bindings import Binding, alias_column, identifier_column

MODULE_SCOPE = "module"
FUNCTION_SCOPE = "function"
CLASS_SCOPE = "class"

STAR = "*"


class Scope:
    """A lexical scope, covering the source lines of the statement that opens it."""

    def __init__(self, kind, node, parent, start, end, tail_end, indent):
        self.kind = kind
        self.node = node
        self.parent = parent
        self.start = start
        self.end = end
        self.tail_end = tail_end
        self.indent = indent
        self.children = []
        self.bindings = []
        if parent is not None:
            parent.children.append(self)

    def define(self, binding):
        self.bindings.append(binding)

    def declared(self, limit=None):
        """Name -> bindings for everything declared here, up to line `limit`."""
        found = {}
        for binding in self.bindings:
            if limit is None or binding.lineno <= limit:
                found.setdefault(binding.name, []).append(binding)
        return found

    def contains(self, line, indent):
        """Whether a cursor belongs here, including the blank tail of a body."""
        if line < self.start:
            return False
        if line <= self.end:
            return True
        return line <= self.tail_end and indent > self.indent


def analyze(tree, lines):
    """Build the scope tree of a parsed module."""
    return _ScopeBuilder(lines).build(tree)


def innermost(scope, line, indent):
    """The deepest scope covering a cursor line typed at `indent`."""
    for child in scope.children:
        if child.contains(line, indent):
            return innermost(child, line, indent)
    return scope


def visible_bindings(module_scope, line, indent):
    """Name -> bindings for every name in scope at a cursor, nearest scope winning.

    The local and global scopes only offer names bound before the cursor line;
    enclosing function scopes offer all of theirs, as closures do at runtime.
    """
    chain = enclosing_chain(innermost(module_scope, line, indent))
    line_bound = {id(chain[0]), id(chain[-1])}
    visible = {}
    for scope in reversed(chain):
        visible.update(scope.declared(line if id(scope) in line_bound else None))
    return visible


def enclosing_chain(scope):
    """The scope plus its enclosing non-class scopes, innermost first.

    Class bodies are skipped: code inside a method cannot see class-level names.
    """
    chain = [scope]
    parent = scope.parent
    while parent is not None:
        if parent.kind != CLASS_SCOPE:
            chain.append(parent)
        parent = parent.parent
    return chain


class _ScopeBuilder:
    """Walks statements, recording what each one binds in the scope it binds it."""

    def __init__(self, lines):
        self._lines = lines
        self._handlers = {
            ast.FunctionDef: self._function,
            ast.AsyncFunctionDef: self._function,
            ast.ClassDef: self._class,
            ast.Import: self._import,
            ast.ImportFrom: self._import,
            ast.Assign: self._assign,
            ast.AnnAssign: self._annotated,
            ast.AugAssign: self._augmented,
            ast.For: self._loop,
            ast.AsyncFor: self._loop,
            ast.With: self._context,
            ast.AsyncWith: self._context,
            ast.Try: self._trapped,
            ast.TryStar: self._trapped,
        }

    def build(self, tree):
        end = max(len(self._lines), 1)
        module = Scope(MODULE_SCOPE, None, None, 1, end, end, -1)
        self._body(module, tree.body, None)
        return module

    def _body(self, scope, statements, owner):
        for statement in statements:
            self._statement(scope, statement, owner)

    def _statement(self, scope, node, owner):
        handler = self._handlers.get(type(node), self._nested)
        handler(scope, node, owner)

    def _nested(self, scope, node, owner):
        """Descend into the blocks of a statement that opens no scope of its own."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self._statement(scope, child, owner)

    def _function(self, scope, node, owner):
        scope.define(self._definition(node, FUNCTION, owner))
        child = self._child(scope, node, FUNCTION_SCOPE)
        receiver = scope.node if scope.kind == CLASS_SCOPE else None
        for position, (argument, default) in enumerate(_parameters(node.args)):
            child.define(
                Binding(
                    name=argument.arg,
                    kind=PARAM,
                    node=argument,
                    lineno=argument.lineno,
                    column=argument.col_offset,
                    value=default,
                    annotation=argument.annotation,
                    receiver=receiver if position == 0 else None,
                    owner=node,
                )
            )
        self._body(child, node.body, node)

    def _class(self, scope, node, owner):
        scope.define(self._definition(node, CLASS, owner))
        self._body(self._child(scope, node, CLASS_SCOPE), node.body, node)

    def _definition(self, node, kind, owner):
        return Binding(
            name=node.name,
            kind=kind,
            node=node,
            lineno=node.lineno,
            column=identifier_column(self._lines, node.lineno, node.name, node.col_offset),
            owner=owner,
        )

    def _import(self, scope, node, owner):
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            scope.define(
                Binding(
                    name=bound,
                    kind=IMPORT,
                    node=node,
                    lineno=alias.lineno,
                    column=alias_column(self._lines, alias),
                    value=alias,
                    owner=owner,
                )
            )

    def _assign(self, scope, node, owner):
        for target in node.targets:
            self._bind(scope, target, node, owner, value=node.value)

    def _annotated(self, scope, node, owner):
        self._bind(scope, node.target, node, owner, node.value, node.annotation)

    def _augmented(self, scope, node, owner):
        self._bind(scope, node.target, node, owner)

    def _loop(self, scope, node, owner):
        self._bind(scope, node.target, node, owner, value=node.iter, kind=TARGET)
        self._nested(scope, node, owner)

    def _context(self, scope, node, owner):
        for item in node.items:
            if item.optional_vars is not None:
                self._bind(scope, item.optional_vars, node, owner, item.context_expr)
        self._nested(scope, node, owner)

    def _trapped(self, scope, node, owner):
        for handler in node.handlers:
            if handler.name:
                scope.define(
                    Binding(
                        name=handler.name,
                        kind=EXCEPT,
                        node=handler,
                        lineno=handler.lineno,
                        column=identifier_column(self._lines, handler.lineno, handler.name),
                        value=handler.type,
                        owner=owner,
                    )
                )
            self._body(scope, handler.body, owner)
        self._nested(scope, node, owner)

    def _bind(self, scope, target, node, owner, value=None, annotation=None, kind=ASSIGN):
        """Record the names a target expression binds, flattening any unpacking."""
        if isinstance(target, ast.Name):
            scope.define(
                Binding(
                    name=target.id,
                    kind=kind,
                    node=node,
                    lineno=target.lineno,
                    column=target.col_offset,
                    value=value,
                    annotation=annotation,
                    owner=owner,
                )
            )
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._bind(scope, element, node, owner, kind=TARGET)
        elif isinstance(target, ast.Starred):
            self._bind(scope, target.value, node, owner, kind=TARGET)

    def _child(self, parent, node, kind):
        text = self._lines[node.lineno - 1]
        indent = len(text) - len(text.lstrip())
        return Scope(kind, node, parent, node.lineno, node.end_lineno,
                     self._blank_tail(node.end_lineno), indent)

    def _blank_tail(self, end):
        """Last line of the run of blank lines following a body.

        A cursor sitting on a fresh, still-empty line is still inside the block
        it is indented into, even though no statement reaches that far.
        """
        index = end
        while index < len(self._lines) and not self._lines[index].strip():
            index += 1
        return index


def _parameters(args):
    """Every parameter a signature binds, in order, paired with its default."""
    positional = args.posonlyargs + args.args
    missing = [None] * (len(positional) - len(args.defaults))
    declared = list(zip(positional, missing + list(args.defaults)))
    declared += list(zip(args.kwonlyargs, args.kw_defaults))
    return declared + [(arg, None) for arg in (args.vararg, args.kwarg) if arg is not None]
