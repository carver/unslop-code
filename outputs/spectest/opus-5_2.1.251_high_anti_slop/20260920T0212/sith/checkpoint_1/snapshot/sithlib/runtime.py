"""Bridging to live objects: importing modules and inspecting what they hold."""

import ast
import builtins
import contextlib
import importlib
import inspect
import sys

from . import symbols


def describe_object(name, obj, lineno=0):
    """Classify a live object as the symbol a user would see for it."""
    if inspect.ismodule(obj):
        return symbols.module(name, lineno)
    if inspect.isclass(obj):
        return symbols.klass(name, lineno)
    if inspect.isroutine(obj):
        return symbols.function(name, lineno)
    return symbols.instance(name, type(obj).__name__, lineno)


def attributes_of(obj):
    """Symbols for the attributes of a live object; modules expose public names only."""
    public_only = inspect.ismodule(obj)
    return [
        describe_object(name, getattr(obj, name, None))
        for name in dir(obj)
        if not (public_only and name.startswith("_"))
    ]


def resolve_expression(node, lookup):
    """Follow a ``a.b.c`` chain to a live object, or ``None`` if it escapes us."""
    if isinstance(node, ast.Name):
        return lookup(node.id)
    if isinstance(node, ast.Attribute):
        parent = resolve_expression(node.value, lookup)
        return None if parent is None else getattr(parent, node.attr, None)
    return None


def import_bindings(node, search_path):
    """Map every name an import statement binds to the object it binds."""
    if isinstance(node, ast.Import):
        return dict(_plain_import(alias, search_path) for alias in node.names)
    return _from_import(node, search_path)


def _plain_import(alias, search_path):
    """``import a.b`` binds ``a``; ``import a.b as c`` binds ``c`` to ``a.b``."""
    if alias.asname:
        return alias.asname, import_module(alias.name, search_path)
    root = alias.name.split(".")[0]
    return root, import_module(root, search_path)


def _from_import(node, search_path):
    module = import_module(node.module, search_path) if node.module else None
    if module is None:
        return {alias.asname or alias.name: None for alias in node.names if alias.name != "*"}
    if any(alias.name == "*" for alias in node.names):
        return {name: getattr(module, name) for name in _star_names(module)}
    return {
        alias.asname or alias.name: _member(module, alias.name, search_path)
        for alias in node.names
    }


def _member(module, name, search_path):
    """An imported member, falling back to the submodule of that name."""
    attribute = getattr(module, name, None)
    if attribute is not None:
        return attribute
    return import_module(f"{module.__name__}.{name}", search_path)


def _star_names(module):
    exported = getattr(module, "__all__", None)
    if exported is not None:
        return [name for name in exported if hasattr(module, name)]
    return [name for name in dir(module) if not name.startswith("_")]


def import_module(name, search_path):
    """Import `name`, letting the analysed file's directory shadow installed packages.

    Importing runs third-party module code, so any failure it raises is simply
    an unresolvable name for our purposes.
    """
    with _path_prefixed(search_path):
        try:
            return importlib.import_module(name)
        except Exception:
            return None


@contextlib.contextmanager
def _path_prefixed(search_path):
    sys.path.insert(0, search_path)
    try:
        yield
    finally:
        sys.path.remove(search_path)


def builtin_symbols():
    """Every name in the builtin scope."""
    return [describe_object(name, getattr(builtins, name)) for name in dir(builtins)]
