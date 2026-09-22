"""Filtering, ordering and serialising completion results."""

from __future__ import annotations

import json
from typing import Iterable, List

from .symbols import KEYWORD, Symbol

PUBLIC, PRIVATE, DUNDER, KEYWORD_GROUP = range(4)


def matches(name: str, prefix: str, fuzzy: bool) -> bool:
    """Whether a name is offered for the typed prefix. Always case-insensitive."""
    if not prefix:
        return True
    if fuzzy:
        return _is_subsequence(prefix.lower(), name.lower())
    return name.lower().startswith(prefix.lower())


def _is_subsequence(query: str, name: str) -> bool:
    """Whether the characters of ``query`` appear in ``name`` in order."""
    remaining = iter(name)
    return all(character in remaining for character in query)


def group_of(symbol: Symbol) -> int:
    """Ordering group: keywords last, then dunder, private and public names."""
    if symbol.kind == KEYWORD:
        return KEYWORD_GROUP
    if symbol.name.startswith("__") and symbol.name.endswith("__"):
        return DUNDER
    if symbol.name.startswith("_"):
        return PRIVATE
    return PUBLIC


def rank(candidates: Iterable[Symbol], prefix: str, fuzzy: bool) -> List[Symbol]:
    """Matching symbols, in the order the spec asks for."""
    chosen = [symbol for symbol in candidates if matches(symbol.name, prefix, fuzzy)]
    return sorted(chosen, key=lambda symbol: (group_of(symbol), symbol.name.lower(), symbol.name))


def payload(candidates: Iterable[Symbol], prefix: str, fuzzy: bool) -> str:
    """The JSON document written to standard output."""
    completions = [
        {
            "name": symbol.name,
            "complete": symbol.name[len(prefix):],
            "type": symbol.kind,
            "description": symbol.description,
        }
        for symbol in rank(candidates, prefix, fuzzy)
    ]
    return json.dumps({"completions": completions}, separators=(",", ":")) + "\n"
