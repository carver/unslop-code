"""Turning a cursor position in a file into ranked completions."""

import keyword
import os

from . import symbols
from .attributes import AttributeResolver
from .index import ModuleIndex
from .matching import matches
from .parsing import parse_tolerant
from .scopes import analyze, visible_names
from .source import locate, read_source


def complete(path, line, column, fuzzy=False):
    """The completion records for the cursor at 1-based `line`, 0-based `column`."""
    source = read_source(path)
    lines = source.splitlines()
    cursor = locate(lines, line, column)

    tree = parse_tolerant(source)
    index = ModuleIndex(tree, os.path.dirname(os.path.abspath(path)))
    visible = visible_names(analyze(tree, lines, index), cursor)

    candidates = _candidates(cursor, visible, index)
    suggested = sorted(
        (symbol for symbol in candidates if matches(symbol.name, cursor.prefix, fuzzy)),
        key=symbols.sort_key,
    )
    return [symbols.as_completion(symbol, len(cursor.prefix)) for symbol in suggested]


def _candidates(cursor, visible, index):
    """Attributes after a dot, otherwise every visible name and the keywords."""
    if cursor.receiver is not None:
        return AttributeResolver(index).resolve(cursor.receiver, visible)
    return list(visible.values()) + [symbols.keyword(word) for word in keyword.kwlist]
