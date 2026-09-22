"""Lexical scopes recovered from a parsed module."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Iterator

from .definitions import Definition
from .namespaces import Namespaces
from .values import Lazy, Value


@dataclass(frozen=True)
class Narrowing:
    """The value a name takes inside one branch of a conditional.

    ``refine`` receives the value the name holds outside the branch, so that
    ``x is not None`` can drop ``None`` from it while ``isinstance`` replaces
    it outright.
    """

    name: str
    start: int
    end: int
    refine: Callable[[Value], Value]


class Binding:
    """A name bound in a scope, together with the site it was written at.

    The value behind the name is produced lazily: resolving it may import a
    module or walk another scope, neither of which is available while the scope
    tree is still being built.  ``conditional`` records that the binding only
    happens on some paths, which is what makes an ``if``/``else`` pair report
    both of its assignments.  ``follow`` is set on a name an import brought in:
    it says where that name was really written.
    """

    def __init__(self, name: str, site: Definition, resolver: Callable[[], Value],
                 conditional: bool = False,
                 follow: Callable[[], list[Definition]] | None = None) -> None:
        self.name = name
        self.site = site
        self.conditional = conditional
        self._value = Lazy(resolver)
        self._follow = follow
        self._following = False

    @property
    def line(self) -> int:
        return self.site.line

    @property
    def imported(self) -> bool:
        """Whether an import statement, rather than this file, wrote the name."""
        return self._follow is not None

    def value(self) -> Value:
        return self._value.value()

    def definition(self) -> Definition:
        """The site, with the kind of an imported name filled in from its value.

        A ``from x import y`` binding only learns whether it names a function,
        a class or a module once the import has been resolved.
        """
        return self.site if self.site.type else replace(self.site, type=self.value().kind)

    def followed(self) -> list[Definition]:
        """Where the import chain this name came through ends.

        A name imported from the standard library, or from a module that does
        not exist, has no source in the project to point at, so the import
        statement itself stands in for it.  So does one whose chain comes back
        round to itself, as ``from . import core`` does inside the package that
        holds ``core``: the chain is not walked twice.
        """
        if self._follow is None or self._following:
            return [self.definition()]
        self._following = True
        try:
            reached = [found for found in self._follow() if found.module_path]
        finally:
            self._following = False
        return reached or [self.definition()]


@dataclass(eq=False)
class Scope:
    """One ``module``, ``function`` or ``class`` namespace.

    ``start``/``end`` delimit the lines the scope owns: from the ``def`` or
    ``class`` line, so that parameters and bases are addressable there, to the
    line before the next sibling statement rather than to the last statement of
    the body, so that a cursor on a trailing blank line still lands inside.
    ``qualified`` is the dotted prefix the names bound here carry.
    ``namespaces`` is carried by the module scope of a file analysed in
    interpreter mode: it is the live counterpart of this namespace, which a
    name the source never binds may still be found in.
    """

    kind: str
    qualified: str
    start: int
    end: int
    parent: Scope | None = None
    bindings: list[Binding] = field(default_factory=list)
    children: list[Scope] = field(default_factory=list)
    narrowings: list[Narrowing] = field(default_factory=list)
    namespaces: Namespaces | None = None

    def child(self, kind: str, name: str, start: int, end: int) -> Scope:
        scope = Scope(kind, f"{self.qualified}.{name}", start, end, self)
        self.children.append(scope)
        return scope

    def descendants(self, *kinds: str) -> Iterator[Scope]:
        """This scope and the ones nested in it, limited to ``kinds`` when named."""
        yield self
        for child in self.children:
            if not kinds or child.kind in kinds:
                yield from child.descendants(*kinds)

    def innermost(self, line: int) -> Scope:
        """The deepest scope owning ``line``."""
        for child in self.children:
            if child.start <= line <= child.end:
                return child.innermost(line)
        return self

    def lookup(self, name: str, line: int) -> list[Binding]:
        """The bindings of ``name`` that can still be in effect at ``line``.

        A scope is searched backwards because later bindings shadow earlier
        ones, and the search stops at the first binding that is not inside a
        conditional branch: a plain reassignment reports only the last binding,
        an ``if``/``else`` pair reports both of its arms.
        """
        for index, scope in enumerate(self._chain()):
            if scope.kind == "class" and index:
                continue  # class bodies are not part of a nested lookup chain
            bound = [binding for binding in scope.bindings if binding.name == name]
            if index == 0 or scope.parent is None:
                # Only names bound above the cursor count -- unless nothing is,
                # in which case a function referring forwards still resolves.
                bound = [binding for binding in bound if binding.line <= line] or bound
            reachable = list(_reachable(bound))
            if reachable:
                return reachable
        return []

    def runtime(self, name: str) -> Value | None:
        """What a live namespace holds for ``name``, outside interpreter mode ``None``."""
        for scope in self._chain():
            if scope.namespaces is not None:
                return scope.namespaces.value(name)
        return None

    def narrowing(self, name: str, line: int) -> Narrowing | None:
        """The innermost branch narrowing ``name`` at ``line``, if any."""
        found = [narrowing for scope in self._chain() for narrowing in scope.narrowings
                 if narrowing.name == name and narrowing.start <= line <= narrowing.end]
        return max(found, key=lambda narrowing: narrowing.start, default=None)

    def visible(self, line: int) -> dict[str, Binding]:
        """Names reachable from this scope at ``line``, innermost binding wins.

        The local and module scopes only expose names bound at or above the
        cursor; enclosing function scopes expose everything they bind.
        """
        found: dict[str, Binding] = {}
        for index, scope in enumerate(self._chain()):
            if scope.kind == "class" and index:
                continue  # class bodies are not part of a nested lookup chain
            limited = index == 0 or scope.parent is None
            bound: dict[str, Binding] = {}
            for binding in scope.bindings:
                if not limited or binding.line <= line:
                    bound[binding.name] = binding
            for name, binding in bound.items():
                found.setdefault(name, binding)
        return found

    def _chain(self) -> Iterator[Scope]:
        scope: Scope | None = self
        while scope is not None:
            yield scope
            scope = scope.parent


def _reachable(bindings: list[Binding]) -> Iterator[Binding]:
    """Bindings from the last backwards, up to and including the first certain one."""
    for binding in reversed(bindings):
        yield binding
        if not binding.conditional:
            return
