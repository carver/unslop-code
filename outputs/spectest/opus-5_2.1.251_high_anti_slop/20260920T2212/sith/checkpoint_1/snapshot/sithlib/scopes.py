"""Lexical scopes recovered from a parsed module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator

from .values import UNKNOWN, Value


@dataclass
class Definition:
    """A name bound in a scope.

    The value behind the name is produced lazily: resolving it may import a
    module or walk another scope, neither of which is available while the
    scope tree is still being built.
    """

    name: str
    line: int
    resolver: Callable[[], Value]
    _value: Value | None = field(default=None, init=False, repr=False)
    _resolving: bool = field(default=False, init=False, repr=False)

    def value(self) -> Value:
        """The value behind the name, resolved at most once.

        Resolution reaches into other modules and can come back round to this
        definition; a name still being resolved is reported as unknown rather
        than chased in circles.
        """
        if self._value is None:
            if self._resolving:
                return UNKNOWN
            self._resolving = True
            try:
                self._value = self.resolver()
            finally:
                self._resolving = False
        return self._value


@dataclass
class Scope:
    """One ``module``, ``function`` or ``class`` namespace.

    ``start``/``end`` delimit the lines the scope owns.  ``end`` extends to the
    line before the next sibling statement rather than to the last statement of
    the body, so that a cursor on a trailing blank line still lands inside.
    """

    kind: str
    start: int
    end: int
    parent: Scope | None = None
    definitions: list[Definition] = field(default_factory=list)
    children: list[Scope] = field(default_factory=list)

    def child(self, kind: str, start: int, end: int) -> Scope:
        scope = Scope(kind, start, end, self)
        self.children.append(scope)
        return scope

    def innermost(self, line: int) -> Scope:
        """The deepest scope owning ``line``."""
        for child in self.children:
            if child.start <= line <= child.end:
                return child.innermost(line)
        return self

    def lookup(self, name: str) -> Definition | None:
        """Resolve ``name`` through the scope chain, latest binding first."""
        for scope in self._chain():
            for definition in reversed(scope.definitions):
                if definition.name == name:
                    return definition
        return None

    def visible(self, line: int) -> dict[str, Definition]:
        """Names reachable from this scope at ``line``, innermost binding wins.

        The local and module scopes only expose names bound at or above the
        cursor; enclosing function scopes expose everything they bind.
        """
        found: dict[str, Definition] = {}
        for index, scope in enumerate(self._chain()):
            if scope.kind == "class" and index:
                continue  # class bodies are not part of a nested lookup chain
            limited = index == 0 or scope.parent is None
            bound: dict[str, Definition] = {}
            for definition in scope.definitions:
                if not limited or definition.line <= line:
                    bound[definition.name] = definition
            for name, definition in bound.items():
                found.setdefault(name, definition)
        return found

    def _chain(self) -> Iterator[Scope]:
        scope: Scope | None = self
        while scope is not None:
            yield scope
            scope = scope.parent
