"""Filtering candidates by the typed prefix and ordering the survivors."""

from __future__ import annotations

from .symbols import KEYWORD, Symbol

PUBLIC, PRIVATE, DUNDER, KEYWORDS = range(4)


def matches(name: str, prefix: str, fuzzy: bool) -> bool:
    """Whether `name` is offered for `prefix`; always case-insensitive."""
    if not prefix:
        return True
    if fuzzy:
        return _is_subsequence(prefix.lower(), name.lower())
    return name.lower().startswith(prefix.lower())


def _is_subsequence(query: str, name: str) -> bool:
    remaining = iter(name)
    return all(character in remaining for character in query)


def group(symbol: Symbol) -> int:
    """The ordering bucket a completion falls into."""
    if symbol.kind == KEYWORD:
        return KEYWORDS
    name = symbol.name
    if name.startswith("__") and name.endswith("__"):
        return DUNDER
    return PRIVATE if name.startswith("_") else PUBLIC


def rank(symbols: list[Symbol]) -> list[Symbol]:
    """Order by group, then case-insensitively by name."""
    return sorted(symbols, key=lambda symbol: (group(symbol), symbol.name.lower(), symbol.name))


def select(symbols: list[Symbol], prefix: str, fuzzy: bool) -> list[dict]:
    """Filter, order, and render the completions for one request.

    The inserted text is the matched name with `len(prefix)` leading characters
    dropped, which is what the spec asks for even when the match differed in
    case or was non-contiguous.
    """
    kept = [symbol for symbol in symbols if matches(symbol.name, prefix, fuzzy)]
    return [
        {
            "name": symbol.name,
            "complete": symbol.name[len(prefix) :],
            "type": symbol.kind,
            "description": symbol.description,
        }
        for symbol in rank(kept)
    ]
