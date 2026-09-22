"""What an import statement names: a module, and the definition behind it.

Relative imports are measured from the project root rather than from a
top-level package: one dot is the directory holding the importing file, and
each further dot climbs one directory.  Climbing past the root leaves the
project, and such an import names nothing.
"""

from __future__ import annotations

from . import scopes
from .definitions import Definition
from .modules import LocalModule, RuntimeModule

#: Binding forms that stand for an import, and so can be followed.
FORMS = (scopes.IMPORT, scopes.FROM_IMPORT)


def absolute(module: LocalModule, level: int, dotted: str) -> str | None:
    """The absolute name of an import seen from `module`, or None above the root."""
    if level == 0:
        return dotted
    package = _package(module)
    if level - 1 > len(package):
        return None
    base = package[: len(package) - level + 1]
    return ".".join([*base, dotted] if dotted else base)


def _package(module: LocalModule) -> list[str]:
    """The dotted parts of the directory holding `module`."""
    parts = module.name.split(".") if module.name else []
    return parts if module.directory else parts[:-1]


def submodule(package: str, name: str) -> str:
    """The dotted name of `name` read as a module sitting inside `package`."""
    return f"{package}.{name}" if package else name


def followed(resolver, binding: scopes.Binding) -> list[Definition]:
    """Where an import binding ultimately leads, or nothing when it leaves the project.

    Only modules inside the project have a definition to land on; a standard
    library or missing module leaves the caller to fall back to the import site.
    """
    dotted = absolute(resolver.module, binding.level, binding.module)
    if dotted is None:
        return []
    if binding.form == scopes.IMPORT:
        return _module(resolver, dotted)
    return _member(resolver, dotted, binding.node.name)


def _member(resolver, dotted: str, name: str) -> list[Definition]:
    """Where `from <dotted> import <name>` leads: a name in a module, or a submodule."""
    handle = resolver.modules.resolve(dotted)
    if isinstance(handle, RuntimeModule):
        return []
    if handle is not None:
        source, bindings = resolver.module_bindings(handle, name)
        if bindings:
            return source.binding_definitions(bindings)
    return _module(resolver, submodule(dotted, name))


def _module(resolver, dotted: str) -> list[Definition]:
    """The record of a project module, or nothing when it lies outside the project."""
    handle = resolver.modules.resolve(dotted)
    return [resolver.module_definition(handle)] if isinstance(handle, LocalModule) else []
