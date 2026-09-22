"""Type information taken from the `.pyi` stub files a project ships.

A module's types may be declared in a stub beside it - ``foo.pyi`` next to
``foo.py`` - or under a ``stubs`` directory at the project root. A stub only
carries declarations: the runtime source stays the place a definition lives,
so stub bindings are layered over the source ones rather than replacing them.
"""

import ast
import os
from dataclasses import replace

from .bindings import CLASS, FUNCTION, Reference
from .modules import STUB_DIRECTORY, STUB_SUFFIX, Context
from .scopes import STAR

_DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
_DECLARED = (CLASS, FUNCTION)


def stub_module(module):
    """The stub declaring the types of `module`, or ``None`` when it has none."""
    if module.path.endswith(STUB_SUFFIX):
        return None
    inline = f"{os.path.splitext(module.path)[0]}{STUB_SUFFIX}"
    if os.path.isfile(inline):
        return module.project.module(inline)
    return stub_named(module.project, module.name)


def stub_named(project, dotted):
    """The stub a dotted module name resolves to inside the project."""
    parts = dotted.split(".")
    roots = (project.root, os.path.join(project.root, STUB_DIRECTORY))
    for base in (os.path.join(root, *parts) for root in roots):
        for candidate in (f"{base}{STUB_SUFFIX}", os.path.join(base, f"__init__{STUB_SUFFIX}")):
            if os.path.isfile(candidate):
                return project.module(candidate)
    return None


def stub_definitions(module, node):
    """The stub's declarations of a class or function written in `module`.

    A stub may declare the same name more than once, as overloads do; every
    declaration is returned, paired with the stub module holding it.
    """
    stub = stub_module(module)
    if stub is None:
        return []
    return [(stub, found) for found in _descend(stub.tree, module.definition_path(node))]


def runtime_definitions(stub, node):
    """The source declarations of a class or function written in a stub."""
    source = _runtime_module(stub)
    if source is None:
        return []
    return [(source, found) for found in _descend(source.tree, stub.definition_path(node))]


def with_stub_types(entries, module, node=None):
    """`entries` with the stub's declarations layered over the names they type.

    `node` is the class whose body the entries come from, or ``None`` for the
    names of the module itself. Classes and functions keep their source
    binding: those values look their own stub up when a signature or a return
    type is wanted. A name only the stub declares is added on its own.
    """
    stub, scope = _stub_scope(module, node)
    if scope is None:
        return entries
    typed = dict(entries)
    for name, bound in scope.declared().items():
        declared = entries.get(name)
        if name == STAR or _is_source_definition(declared):
            continue
        reference = Reference(stub, bound[-1])
        typed[name] = (replace(declared, typed=reference)
                       if isinstance(declared, Reference) else reference)
    return typed


def annotation_for(binding, context):
    """Where a parameter's type is written: the stub's annotation, else its own."""
    for stub, function in stub_definitions(context.module, binding.owner):
        declared = _declared_parameter(function, binding.name)
        if declared is not None and declared.annotation is not None:
            return declared.annotation, Context(stub, function.lineno, function.col_offset)
    return binding.annotation, context


def _runtime_module(stub):
    """The module a stub declares the types of, when the project holds its source."""
    if not stub.path.endswith(STUB_SUFFIX):
        return None
    inline = f"{os.path.splitext(stub.path)[0]}.py"
    if os.path.isfile(inline):
        return stub.project.module(inline)
    found = stub.project.module_named(stub.name)
    return None if found is None or found.path.endswith(STUB_SUFFIX) else found


def _stub_scope(module, node):
    """The stub scope holding the names of a module or of one of its classes."""
    if node is None:
        stub = stub_module(module)
        return (stub, stub.scope) if stub is not None else (None, None)
    declared = stub_definitions(module, node)
    if not declared:
        return None, None
    stub, found = declared[0]
    return stub, stub.scope_for(found)


def _is_source_definition(entry):
    return isinstance(entry, Reference) and entry.binding.kind in _DECLARED


def _descend(node, path):
    """The declarations reached by following a chain of names into a module."""
    if not path:
        return [node]
    return [
        found
        for child in ast.iter_child_nodes(node)
        if isinstance(child, _DEFINITIONS) and child.name == path[0]
        for found in _descend(child, path[1:])
    ]


def _declared_parameter(function, name):
    """The parameter of a signature that goes by `name`, wherever it is declared."""
    arguments = function.args
    declared = (arguments.posonlyargs + arguments.args + arguments.kwonlyargs
                + [arguments.vararg, arguments.kwarg])
    return next((argument for argument in declared
                 if argument is not None and argument.arg == name), None)
