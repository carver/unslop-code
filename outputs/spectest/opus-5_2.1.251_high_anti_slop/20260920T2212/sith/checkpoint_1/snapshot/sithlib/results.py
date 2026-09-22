"""Matching a typed prefix against symbols and ordering the results."""

from __future__ import annotations

import builtins
import keyword
from dataclasses import asdict, dataclass
from typing import Iterable

from .values import Keyword, Symbol, runtime_value


@dataclass(frozen=True)
class Completion:
    """One entry of the JSON output."""

    name: str
    complete: str
    type: str
    description: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def builtin_symbols() -> list[Symbol]:
    """Names from the builtin scope, excluding those that are keywords."""
    return [Symbol(name, runtime_value(getattr(builtins, name), name))
            for name in dir(builtins) if not keyword.iskeyword(name)]


def keyword_symbols() -> list[Symbol]:
    return [Symbol(word, Keyword(word)) for word in keyword.kwlist]


def build_completions(symbols: Iterable[Symbol], prefix: str, fuzzy: bool) -> list[Completion]:
    """Filter ``symbols`` by ``prefix`` and sort them into the output order."""
    matched = [
        Completion(symbol.name, symbol.name[len(prefix):], symbol.value.kind,
                   symbol.value.description)
        for symbol in symbols if matches(symbol.name, prefix, fuzzy)
    ]
    return sorted(matched, key=_order)


def matches(name: str, prefix: str, fuzzy: bool) -> bool:
    """Case insensitive prefix match, or subsequence match when ``fuzzy``."""
    if not prefix:
        return True
    name, prefix = name.lower(), prefix.lower()
    if not fuzzy:
        return name.startswith(prefix)
    remaining = iter(name)
    return all(character in remaining for character in prefix)


def _order(completion: Completion) -> tuple[int, str]:
    return _group(completion), completion.name.lower()


def _group(completion: Completion) -> int:
    """Public names first, then private, then dunders, then keywords."""
    name = completion.name
    if completion.type == "keyword":
        return 3
    if name.startswith("__") and name.endswith("__"):
        return 2
    return 1 if name.startswith("_") else 0
