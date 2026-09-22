"""Filtering candidates by the typed prefix and ordering the survivors."""

from __future__ import annotations

from .settings import Settings
from .symbols import CLASS, FUNCTION, KEYWORD, Symbol

PUBLIC, PRIVATE, DUNDER, KEYWORDS = range(4)

#: The completions `add_bracket` writes a call's opening bracket after.
CALLABLE_KINDS = (FUNCTION, CLASS)


def matches(name: str, prefix: str, fuzzy: bool, case_insensitive: bool = True) -> bool:
    """Whether `name` is offered for `prefix`, in either case or in the one typed."""
    if not prefix:
        return True
    wanted, target = (prefix.lower(), name.lower()) if case_insensitive else (prefix, name)
    return _is_subsequence(wanted, target) if fuzzy else target.startswith(wanted)


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


def select(symbols: list[Symbol], prefix: str, fuzzy: bool,
           settings: Settings = Settings()) -> list[dict]:
    """Filter, order, and render the completions for one request.

    The inserted text is the matched name with `len(prefix)` leading characters
    dropped, which is what the spec asks for even when the match differed in
    case or was non-contiguous.
    """
    kept = [s for s in symbols if matches(s.name, prefix, fuzzy, settings.case_insensitive)]
    return [
        {
            "name": symbol.name,
            "complete": _inserted(symbol, prefix, settings),
            "type": symbol.kind,
            "description": symbol.description,
        }
        for symbol in rank(kept)
    ]


def _inserted(symbol: Symbol, prefix: str, settings: Settings) -> str:
    """What typing the completion adds, with the bracket of a call when asked for."""
    bracket = "(" if settings.add_bracket and symbol.kind in CALLABLE_KINDS else ""
    return symbol.name[len(prefix) :] + bracket
