"""Filtering, ordering and serialising completion results."""

from __future__ import annotations

import json
from typing import Iterable, List

from .settings import Settings
from .symbols import CLASS, FUNCTION, KEYWORD, Symbol

PUBLIC, PRIVATE, DUNDER, KEYWORD_GROUP = range(4)
BRACKETED = (FUNCTION, CLASS)
"""Kinds whose completion may insert the bracket that calls them."""


def matches(name: str, prefix: str, fuzzy: bool, case_insensitive: bool = True) -> bool:
    """Whether a name is offered for the typed prefix."""
    if not prefix:
        return True
    written, typed = (name.lower(), prefix.lower()) if case_insensitive else (name, prefix)
    if fuzzy:
        return _is_subsequence(typed, written)
    return written.startswith(typed)


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


def rank(candidates: Iterable[Symbol], prefix: str, fuzzy: bool, settings: Settings) -> List[Symbol]:
    """Matching symbols, in the order the spec asks for."""
    chosen = [
        symbol for symbol in candidates
        if matches(symbol.name, prefix, fuzzy, settings.case_insensitive)
    ]
    return sorted(chosen, key=lambda symbol: (group_of(symbol), symbol.name.lower(), symbol.name))


def payload(candidates: Iterable[Symbol], prefix: str, fuzzy: bool, settings: Settings) -> str:
    """The JSON document written to standard output."""
    completions = [
        {
            "name": symbol.name,
            "complete": inserted(symbol, prefix, settings),
            "type": symbol.kind,
            "description": symbol.description,
        }
        for symbol in rank(candidates, prefix, fuzzy, settings)
    ]
    return json.dumps({"completions": completions}, separators=(",", ":")) + "\n"


def inserted(symbol: Symbol, prefix: str, settings: Settings) -> str:
    """The text a completion writes: the name, less what was already typed."""
    written = symbol.name[len(prefix):]
    if settings.add_bracket and symbol.kind in BRACKETED:
        return written + "("
    return written
