"""Following an import binding through to the definition it finally names.

`goto --follow-imports` walks from the import statement under the cursor into
the module it names, and on through any import it finds there. A hop that
cannot be walked - a module outside the project, a name the module does not
bind, or an import cycle - leaves the import site itself as the answer.
"""

from __future__ import annotations

import ast
from typing import List, Optional

from .analysis import SourceModule, definitions_of
from .definitions import Definition
from .importing import IMPORT_NODES, STAR, alias_for, imported_module
from .symbols import MODULE, Symbol


def followed(symbol: Symbol) -> List[Definition]:
    """Where the target of an import binding is defined."""
    walked = set()
    current = symbol
    while isinstance(current.node, IMPORT_NODES):
        step = (current.origin.module_path, current.lineno, current.name)
        target = None if step in walked else _target(current)
        if target is None:
            return definitions_of(symbol)
        walked.add(step)
        current = target
    return definitions_of(current)


def _target(symbol: Symbol) -> Optional[Symbol]:
    """The binding one import hop points at, in the module it names."""
    if isinstance(symbol.node, ast.Import):
        return _module_target(symbol)
    return _name_target(symbol)


def _module_target(symbol: Symbol) -> Optional[Symbol]:
    """`import x` names a module, which stands as its own definition."""
    alias = alias_for(symbol.node, symbol.name)
    module = symbol.origin.project.module(imported_module(alias)) if alias else None
    if not isinstance(module, SourceModule):
        return None
    return Symbol(symbol.name, MODULE, value=module)


def _name_target(symbol: Symbol) -> Optional[Symbol]:
    """The binding `from x import name` reaches, under the name `x` gives it."""
    node = symbol.node
    module = symbol.origin.project.module_for(symbol.origin, node.level, node.module or "")
    if not isinstance(module, SourceModule):
        return None
    alias = alias_for(node, symbol.name)
    wanted = alias.name if alias is not None and alias.name != STAR else symbol.name
    found = module.attributes(wanted)
    return found[0] if found else None
