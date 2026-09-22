"""What a piece of source denotes, and what can be asked of it.

A *target* is a module, a class, an instance or a function.  Targets know how to
list their attributes, which is what completion after a `.` needs, and how to
present themselves as a definition, which is what `infer` answers with.  The
ones that stand for code in the project delegate both to the resolver that
found them; the ones that stand for a live object answer from the object.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import definitions
from .definitions import Definition
from .symbols import CLASS, FUNCTION, INSTANCE, MODULE, STATEMENT, Symbol, classify, describe

if TYPE_CHECKING:
    from .resolve import Resolver

MISSING = object()


class Target:
    """Something a name can refer to."""

    kind = STATEMENT
    type_name: str | None = None

    def attributes(self) -> list[Symbol]:
        return []

    def attribute(self, name: str) -> list["Target"]:
        return []

    def member_definitions(self, name: str) -> list[Definition]:
        """Where an attribute of this target is defined, for `goto`."""
        return []

    def called(self) -> list["Target"]:
        """The result of calling this target: an instance, or a return type."""
        return []

    def definition(self) -> Definition | None:
        return None


class RuntimeTarget(Target):
    """A live object reached through an imported module or through builtins."""

    def __init__(self, obj: object, name: str | None = None) -> None:
        self.obj = obj
        self.kind = classify(obj)
        self.type_name = definitions.type_name(type(obj))
        self.name = name or getattr(obj, "__name__", self.type_name)

    def attributes(self) -> list[Symbol]:
        names = dir(self.obj)
        if self.kind == MODULE:
            names = [name for name in names if not name.startswith("_")]
        return [Symbol.from_object(name, getattr(self.obj, name, None)) for name in names]

    def attribute(self, name: str) -> list[Target]:
        member = getattr(self.obj, name, MISSING)
        return [] if member is MISSING else [RuntimeTarget(member, name)]

    def member_definitions(self, name: str) -> list[Definition]:
        return [target.definition() for target in self.attribute(name)]

    def called(self) -> list[Target]:
        return [RuntimeInstanceTarget(self.obj)] if self.kind == CLASS else []

    def definition(self) -> Definition:
        if self.kind == INSTANCE:
            return RuntimeInstanceTarget(type(self.obj)).definition()
        description = describe(self.kind, self.name, self.type_name)
        return definitions.from_object(self.name, self.obj, self.kind, description)


class RuntimeInstanceTarget(Target):
    """An instance of a live class, such as a literal or `list()`."""

    kind = INSTANCE

    def __init__(self, cls: type) -> None:
        self.cls = cls
        self.type_name = definitions.type_name(cls)

    def attributes(self) -> list[Symbol]:
        return [Symbol.from_object(name, getattr(self.cls, name, None)) for name in dir(self.cls)]

    def attribute(self, name: str) -> list[Target]:
        member = getattr(self.cls, name, MISSING)
        return [] if member is MISSING else [RuntimeTarget(member, name)]

    def member_definitions(self, name: str) -> list[Definition]:
        return [target.definition() for target in self.attribute(name)]

    def definition(self) -> Definition:
        if getattr(self.cls, "__module__", None) == definitions.BUILTINS:
            return definitions.builtin(self.type_name)
        description = describe(INSTANCE, self.type_name, self.type_name)
        return definitions.from_object(self.type_name, self.cls, INSTANCE, description)


class ModuleTarget(Target):
    """An imported module, whether a project file or an installed package."""

    kind = MODULE

    def __init__(self, handle, resolver: "Resolver") -> None:
        self.handle = handle
        self.resolver = resolver

    def attributes(self) -> list[Symbol]:
        return self.resolver.module_symbols(self.handle)

    def attribute(self, name: str) -> list[Target]:
        return self.resolver.member_targets(self.handle, name)

    def member_definitions(self, name: str) -> list[Definition]:
        return self.resolver.member_definitions(self.handle, name)

    def definition(self) -> Definition:
        return self.resolver.module_definition(self.handle)


class ClassTarget(Target):
    """A class defined in the file being analysed."""

    kind = CLASS

    def __init__(self, node: ast.ClassDef, resolver: "Resolver") -> None:
        self.node = node
        self.resolver = resolver

    def attributes(self) -> list[Symbol]:
        return self.resolver.class_symbols(self.node)

    def attribute(self, name: str) -> list[Target]:
        found = self.resolver.class_members(self.node, name)
        return self.resolver.binding_targets(found) or self.resolver.stub_members(name, self.node)

    def member_definitions(self, name: str) -> list[Definition]:
        found = self.resolver.class_members(self.node, name)
        return self.resolver.binding_definitions(
            found
        ) or self.resolver.stub_member_definitions(name, self.node)

    def called(self) -> list[Target]:
        return [InstanceTarget(self.node, self.resolver)]

    def definition(self) -> Definition:
        return self.resolver.class_definition(self.node, CLASS)


class InstanceTarget(Target):
    """An instance of a class defined in the file being analysed."""

    kind = INSTANCE

    def __init__(self, node: ast.ClassDef, resolver: "Resolver") -> None:
        self.node = node
        self.resolver = resolver
        self.type_name = node.name

    def attributes(self) -> list[Symbol]:
        return self.resolver.instance_symbols(self.node)

    def attribute(self, name: str) -> list[Target]:
        found = self.resolver.instance_members(self.node, name)
        return self.resolver.binding_targets(found) or self.resolver.stub_members(name, self.node)

    def member_definitions(self, name: str) -> list[Definition]:
        found = self.resolver.instance_members(self.node, name)
        return self.resolver.binding_definitions(
            found
        ) or self.resolver.stub_member_definitions(name, self.node)

    def definition(self) -> Definition:
        return self.resolver.class_definition(self.node, INSTANCE)


class FunctionTarget(Target):
    """A function or method defined in the file being analysed."""

    kind = FUNCTION

    def __init__(self, node: ast.AST, resolver: "Resolver") -> None:
        self.node = node
        self.resolver = resolver

    def called(self) -> list[Target]:
        return self.resolver.returned(self.node)

    def definition(self) -> Definition:
        return self.resolver.function_definition(self.node)


def is_none(target: Target) -> bool:
    """Whether a target stands for `None`, which narrowing needs to rule out."""
    return isinstance(target, RuntimeInstanceTarget) and target.cls is type(None)
