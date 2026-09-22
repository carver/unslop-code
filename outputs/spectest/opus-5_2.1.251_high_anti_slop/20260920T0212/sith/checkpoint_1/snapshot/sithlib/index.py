"""Module-wide facts collected once, before any scope is walked."""

import ast
import builtins

from .runtime import import_bindings

_IMPORT_NODES = (ast.Import, ast.ImportFrom)


class ModuleIndex:
    """The classes a file defines and the objects its imports bind.

    Both are collected from the whole tree so that a name can be resolved even
    when it is defined further down the file than the code referring to it.
    """

    def __init__(self, tree, search_path):
        self.search_path = search_path
        self.classes = {
            node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        }
        self.bindings = {
            node: import_bindings(node, search_path)
            for node in ast.walk(tree)
            if isinstance(node, _IMPORT_NODES)
        }
        self.objects = {
            name: obj for binding in self.bindings.values() for name, obj in binding.items()
        }

    def lookup(self, name):
        """The live object a name refers to: an imported one, else a builtin."""
        if name in self.objects:
            return self.objects[name]
        return getattr(builtins, name, None)
