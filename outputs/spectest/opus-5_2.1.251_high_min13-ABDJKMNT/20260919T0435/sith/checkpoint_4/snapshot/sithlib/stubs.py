"""Type information taken from `.pyi` stub files.

A stub shadows the module it describes: the annotations it writes are what
`infer`, `signatures` and `complete` report, while `goto` keeps pointing at the
real source.  A stub is looked for beside the module it stubs and then in a
`stubs/` directory in the project root.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import scopes

if TYPE_CHECKING:
    from .definitions import Definition
    from .modules import LocalModule
    from .resolve import Resolver
    from .symbols import Symbol
    from .targets import Target

SUFFIX = ".pyi"
DIRECTORY = "stubs"
PACKAGE = f"__init__{SUFFIX}"


def search_paths(root: str, dotted: str) -> list[str]:
    """Where a module's stub may live, the inline stub first."""
    parts = dotted.split(".")
    beside = os.path.join(root, *parts)
    collected = os.path.join(root, DIRECTORY, *parts)
    return [
        f"{beside}{SUFFIX}",
        os.path.join(beside, PACKAGE),
        f"{collected}{SUFFIX}",
        os.path.join(collected, PACKAGE),
    ]


@dataclass(frozen=True)
class Stub:
    """A parsed `.pyi`, read through a resolver of its own.

    Names are addressed by the chain of classes that encloses them, so
    `("Box",), "size"` is the `size` attribute declared in `class Box`.
    """

    module: "LocalModule"
    tree: scopes.ScopeTree
    resolver: "Resolver"

    def bindings(self, owners: list[str], name: str) -> list[scopes.Binding]:
        """Everything the stub declares under `name` in that scope."""
        scope = self._scope(owners)
        return [binding for binding in scope.bindings if binding.name == name] if scope else []

    def functions(self, owners: list[str], name: str) -> list[ast.AST]:
        """The `def name` declarations there; more than one when overloaded."""
        return [b.node for b in self.bindings(owners, name) if b.form == scopes.DEF]

    def annotated(self, owners: list[str], name: str) -> list["Target"]:
        """What the annotation on a declared name evaluates to, if it has one."""
        declared = [b for b in self.bindings(owners, name) if b.annotation is not None]
        return self.resolver.binding_targets(declared)

    def targets(self, owners: list[str], name: str) -> list["Target"]:
        return self.resolver.binding_targets(self.bindings(owners, name))

    def definitions(self, owners: list[str], name: str) -> list["Definition"]:
        return self.resolver.binding_definitions(self.bindings(owners, name))

    def symbols(self, owners: list[str]) -> dict[str, "Symbol"]:
        """The names declared in one stub scope, for completion."""
        scope = self._scope(owners)
        if scope is None:
            return {}
        return {binding.name: self.resolver.symbol(binding) for binding in scope.bindings}

    def instances(self, annotations: list[ast.expr]) -> list["Target"]:
        """Instances of the types the stub's own annotations name."""
        return self.resolver.instances(annotations, self.tree.root)

    def _scope(self, owners: list[str]) -> scopes.Scope | None:
        scope = self.tree.root
        for name in owners:
            scope = next((c for c in scope.children if _named(c, name)), None)
            if scope is None:
                return None
        return scope


def _named(scope: scopes.Scope, name: str) -> bool:
    return getattr(scope.node, "name", None) == name
