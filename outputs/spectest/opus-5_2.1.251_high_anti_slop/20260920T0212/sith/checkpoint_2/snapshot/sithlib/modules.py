"""The files under analysis: how they are loaded, named and navigated."""

import ast
import os
from dataclasses import dataclass

from .parsing import parse_tolerant
from .scopes import analyze
from .source import read_source

_DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


class Module:
    """One parsed source file: its scope tree and the names it can qualify."""

    def __init__(self, project, path, source):
        self.project = project
        self.path = os.path.abspath(path)
        self.lines = source.splitlines()
        self.tree = parse_tolerant(source)
        self.scope = analyze(self.tree, self.lines)
        self._scopes = _scopes_by_node(self.scope)
        self._owners = _owners_by_node(self.tree)

    @property
    def name(self):
        """Dotted module name, taken from the path relative to the project root."""
        stem = os.path.splitext(self.relative_path)[0].replace(os.sep, ".")
        return stem[: -len(".__init__")] if stem.endswith(".__init__") else stem

    @property
    def relative_path(self):
        return self.project.relative(self.path)

    def scope_for(self, node):
        """The scope a class or function body opens."""
        return self._scopes.get(id(node))

    def qualified(self, name, owner):
        """Dotted name of `name` as defined inside `owner`, or at module level."""
        parts = []
        while owner is not None:
            parts.append(owner.name)
            owner = self._owners.get(id(owner))
        return ".".join([self.name] + list(reversed(parts)) + [name])

    def qualified_name(self, node):
        """Dotted name of a class or function defined in this module."""
        return self.qualified(node.name, self._owners.get(id(node)))

    def enclosing_class(self, node):
        """The class a method is defined in, or ``None`` for a plain function."""
        owner = self._owners.get(id(node))
        return owner if isinstance(owner, ast.ClassDef) else None


@dataclass(frozen=True)
class Context:
    """The position an expression is evaluated at: a module and a cursor line."""

    module: Module
    line: int
    indent: int = 0

    def at(self, node):
        """The same module, positioned at a node inside it."""
        return Context(self.module, node.lineno, node.col_offset)


class Project:
    """A root directory and the modules parsed from it, each parsed once."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._modules = {}

    def module(self, path):
        """The parsed module for a source file."""
        absolute = os.path.abspath(path)
        if absolute not in self._modules:
            self._modules[absolute] = Module(self, absolute, read_source(absolute))
        return self._modules[absolute]

    def module_named(self, dotted):
        """The module a dotted import name refers to inside the project, if any."""
        return self.module_at(os.path.join(self.root, *dotted.split(".")))

    def module_at(self, base):
        """The module stored at a path without its extension, if any."""
        for candidate in (f"{base}.py", os.path.join(base, "__init__.py")):
            if os.path.isfile(candidate):
                return self.module(candidate)
        return None

    def relative(self, path):
        """`path` relative to the project root, or absolute when it lies outside."""
        if os.path.commonpath([self.root, path]) == self.root:
            return os.path.relpath(path, self.root)
        return path


def _scopes_by_node(scope, found=None):
    found = {} if found is None else found
    for child in scope.children:
        found[id(child.node)] = child
        _scopes_by_node(child, found)
    return found


def _owners_by_node(node, owner=None, owners=None):
    """Map each class or function node to the definition that encloses it."""
    owners = {} if owners is None else owners
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _DEFINITIONS):
            owners[id(child)] = owner
            _owners_by_node(child, child, owners)
        else:
            _owners_by_node(child, owner, owners)
    return owners
