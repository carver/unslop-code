"""The files under analysis: how they are loaded, named and navigated."""

import ast
import os
from dataclasses import dataclass

from .errors import SithError
from .parsing import parse_tolerant
from .scopes import analyze
from .source import read_source

STUB_SUFFIX = ".pyi"
STUB_DIRECTORY = "stubs"

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
        """Dotted module name, taken from the path relative to the project root.

        A stub of the project's stub directory is named after the module it
        types rather than after the directory it is filed under.
        """
        stem = os.path.splitext(self.relative_path)[0].replace("/", ".")
        if self.path.endswith(STUB_SUFFIX) and stem.startswith(f"{STUB_DIRECTORY}."):
            stem = stem[len(STUB_DIRECTORY) + 1:]
        return stem[: -len(".__init__")] if stem.endswith(".__init__") else stem

    @property
    def relative_path(self):
        return self.project.relative(self.path)

    def submodules(self):
        """Name -> module for the submodules this module holds, if it is a package."""
        if os.path.basename(self.path) != "__init__.py":
            return {}
        directory = os.path.dirname(self.path)
        return {
            name: self.project.module_at(os.path.join(directory, name))
            for name in self.project.submodule_names(directory)
        }

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
        return ".".join([self.name] + self.definition_path(node))

    def definition_path(self, node):
        """The names leading to a class or function inside this module."""
        parts = []
        while node is not None:
            parts.append(node.name)
            node = self._owners.get(id(node))
        return list(reversed(parts))

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
        """The module stored inside the project at a path without its extension.

        A module declared by a stub alone is read from the stub. A directory
        holding no ``__init__.py`` is a namespace package: it can be imported
        and holds submodules, but contributes no names of its own. Paths
        outside the project root hold nothing an import can reach.
        """
        if not self.contains(base):
            return None
        for candidate in (f"{base}.py", os.path.join(base, "__init__.py"),
                          f"{base}{STUB_SUFFIX}",
                          os.path.join(base, f"__init__{STUB_SUFFIX}")):
            if os.path.isfile(candidate):
                return self.module(candidate)
        return self._namespace(base) if os.path.isdir(base) else None

    def submodule_names(self, base):
        """Names of the modules and packages stored directly inside a directory."""
        if not (self.contains(base) and os.path.isdir(base)):
            return []
        return sorted(
            entry[:-3] if entry.endswith(".py") else entry
            for entry in os.listdir(base)
            if _importable(base, entry)
        )

    def source_paths(self, suffix=".py"):
        """Every source file stored inside the project, in a stable order."""
        found = []
        for directory, inside, files in os.walk(self.root):
            inside[:] = sorted(name for name in inside
                               if not name.startswith(".") and name != "__pycache__")
            found.extend(os.path.join(directory, name)
                         for name in sorted(files) if name.endswith(suffix))
        return found

    def contains(self, path):
        """Whether a path lies inside the project root."""
        absolute = os.path.abspath(path)
        return os.path.commonpath([self.root, absolute]) == self.root

    def relative(self, path):
        """`path` relative to the root in POSIX form, or absolute when outside it."""
        inside = self.contains(path)
        return (os.path.relpath(path, self.root) if inside else path).replace(os.sep, "/")

    def _namespace(self, base):
        """The empty module standing for a package directory with no ``__init__.py``."""
        path = os.path.join(base, "__init__.py")
        if path not in self._modules:
            self._modules[path] = Module(self, path, "")
        return self._modules[path]


def project_for(path, root=None):
    """The project a file is analysed in: the given root, else the file's directory."""
    if root is None:
        return Project(os.path.dirname(os.path.abspath(path)))
    return project_at(root)


def project_at(root):
    """The project rooted at `root`, defaulting to the working directory."""
    if root is None:
        return Project(os.getcwd())
    if not os.path.isdir(root):
        raise SithError(f"not a project directory: {root}")
    return Project(root)


def _importable(base, entry):
    """Whether a directory entry can be imported under a name of its own."""
    if entry.endswith(".py"):
        return entry != "__init__.py" and entry[:-3].isidentifier()
    return (entry.isidentifier() and entry != "__pycache__"
            and os.path.isdir(os.path.join(base, entry)))


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
