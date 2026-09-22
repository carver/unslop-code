"""Lexical scopes: which names exist where, and which ones a cursor can see."""

import ast

from . import symbols
from .inference import assignment_symbol
from .runtime import builtin_symbols, describe_object

MODULE_SCOPE = "module"
FUNCTION_SCOPE = "function"
CLASS_SCOPE = "class"


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
        self._symbols = []
        if parent is not None:
            parent.children.append(self)

    def define(self, symbol):
        self._symbols.append(symbol)

    def defined(self, limit=None):
        """Name -> symbol for everything declared here, up to line `limit`."""
        return {
            symbol.name: symbol
            for symbol in self._symbols
            if limit is None or symbol.lineno <= limit
        }

    def contains(self, line, indent):
        """Whether a cursor belongs here, including the blank tail of a body."""
        if line < self.start:
            return False
        if line <= self.end:
            return True
        return line <= self.tail_end and indent > self.indent


def analyze(tree, lines, index):
    """Build the scope tree of a parsed module."""
    return _ScopeBuilder(lines, index).build(tree)


def innermost(scope, line, indent):
    """The deepest scope covering a cursor line typed at `indent`."""
    for child in scope.children:
        if child.contains(line, indent):
            return innermost(child, line, indent)
    return scope


def visible_names(module_scope, cursor):
    """Name -> symbol for every name in scope at the cursor, nearest scope winning.

    The local and global scopes only offer names bound before the cursor line;
    enclosing function scopes offer all of theirs, as closures do at runtime.
    """
    chain = _enclosing_chain(innermost(module_scope, cursor.line, cursor.indent))
    line_bound = {id(chain[0]), id(chain[-1])}
    visible = {symbol.name: symbol for symbol in builtin_symbols()}
    for scope in reversed(chain):
        visible.update(scope.defined(cursor.line if id(scope) in line_bound else None))
    return visible


def _enclosing_chain(scope):
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

    def __init__(self, lines, index):
        self._lines = lines
        self._index = index
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
        self._body(module, tree.body)
        return module

    def _body(self, scope, statements):
        for statement in statements:
            self._statement(scope, statement)

    def _statement(self, scope, node):
        handler = self._handlers.get(type(node), self._nested)
        handler(scope, node)

    def _nested(self, scope, node):
        """Descend into the blocks of a statement that opens no scope of its own."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self._statement(scope, child)

    def _function(self, scope, node):
        scope.define(symbols.function(node.name, node.lineno))
        child = self._child(scope, node, FUNCTION_SCOPE)
        receiver = scope.node.name if scope.kind == CLASS_SCOPE else None
        for position, name in enumerate(_parameter_names(node.args)):
            child.define(symbols.param(name, node.lineno, receiver if position == 0 else None))
        self._body(child, node.body)

    def _class(self, scope, node):
        scope.define(symbols.klass(node.name, node.lineno))
        self._body(self._child(scope, node, CLASS_SCOPE), node.body)

    def _import(self, scope, node):
        unresolved = symbols.module if isinstance(node, ast.Import) else symbols.statement
        for name, obj in self._index.bindings[node].items():
            if obj is None:
                scope.define(unresolved(name, node.lineno))
            else:
                scope.define(describe_object(name, obj, node.lineno))

    def _assign(self, scope, node):
        for target in node.targets:
            self._bind(scope, target, node.value, node.lineno)

    def _annotated(self, scope, node):
        self._bind(scope, node.target, node.value, node.lineno, node.annotation)

    def _augmented(self, scope, node):
        self._bind(scope, node.target, None, node.lineno)

    def _loop(self, scope, node):
        self._bind(scope, node.target, None, node.lineno)
        self._nested(scope, node)

    def _context(self, scope, node):
        for item in node.items:
            if item.optional_vars is not None:
                self._bind(scope, item.optional_vars, item.context_expr, node.lineno)
        self._nested(scope, node)

    def _trapped(self, scope, node):
        for handler in node.handlers:
            if handler.name:
                scope.define(symbols.statement(handler.name, handler.lineno))
            self._body(scope, handler.body)
        self._nested(scope, node)

    def _bind(self, scope, target, value, lineno, annotation=None):
        if isinstance(target, ast.Name):
            scope.define(
                assignment_symbol(target.id, value, lineno, self._index, annotation)
            )
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._bind(scope, element, None, lineno)
        elif isinstance(target, ast.Starred):
            self._bind(scope, target.value, None, lineno)

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


def _parameter_names(args):
    """Every parameter a signature binds, in declaration order."""
    declared = args.posonlyargs + args.args + args.kwonlyargs
    collected = [arg.arg for arg in declared]
    return collected + [arg.arg for arg in (args.vararg, args.kwarg) if arg is not None]
