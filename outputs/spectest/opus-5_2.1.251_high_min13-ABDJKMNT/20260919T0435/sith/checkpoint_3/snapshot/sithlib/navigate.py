"""The `infer` and `goto` commands: what a name means, and where it came from."""

from __future__ import annotations

from . import cursor, definitions
from .analysis import Analysis
from .definitions import Definition
from .source import SithError
from .targets import Target


def infer(path: str, line: int, col: int, project: str | None = None) -> list[dict]:
    """What the name at the cursor evaluates to, as definition records."""
    analysis, reference = _at_cursor(path, line, col, project)
    return definitions.render(_definitions_of(_evaluated(analysis, reference)))


def goto(path: str, line: int, col: int, project: str | None = None,
         follow: bool = False) -> list[dict]:
    """Where the name at the cursor was defined, as definition records.

    With `follow`, a name that was imported is chased through the import chain
    into the module that really defines it.
    """
    analysis, reference = _at_cursor(path, line, col, project, follow)
    if reference.name is None:
        return []  # a literal is written where it stands, so it is defined nowhere
    return definitions.render(_bindings_of(analysis, reference))


def _at_cursor(path: str, line: int, col: int, project: str | None = None,
               follow: bool = False) -> tuple[Analysis, cursor.Reference]:
    analysis = Analysis.at(path, line, col, project, follow)
    reference = cursor.reference_at(analysis.line_text, col)
    if reference is None:
        raise SithError(f"no name at line {line}, column {col}")
    return analysis, reference


def _evaluated(analysis: Analysis, reference: cursor.Reference) -> list[Target]:
    """What the cursor's expression is worth, following any definition it rests on."""
    defined = _defined_at_cursor(analysis, reference)
    if defined:
        return analysis.resolver.binding_targets(defined)
    return analysis.resolver.source(reference.source, analysis.scope)


def _defined_at_cursor(analysis: Analysis, reference: cursor.Reference):
    """The binding the cursor rests on, when it is sitting on its very identifier."""
    if reference.name is None or reference.receiver is not None:
        return []
    return analysis.resolver.binding_at(reference.name, analysis.line, reference.start)


def _bindings_of(analysis: Analysis, reference: cursor.Reference) -> list[Definition]:
    """Where a bare name was bound, or where its owner defines the attribute."""
    resolver, scope = analysis.resolver, analysis.scope
    if reference.receiver is not None:
        owners = resolver.source(reference.receiver, scope)
        return [record for owner in owners for record in owner.member_definitions(reference.name)]
    bindings = _defined_at_cursor(analysis, reference) or resolver.bindings_for(
        reference.name, scope
    )
    if bindings:
        return resolver.binding_definitions(bindings)
    # Nothing in the file binds the name: it can still be a builtin.
    return _definitions_of(resolver.name(reference.name, scope))


def _definitions_of(targets: list[Target]) -> list[Definition]:
    found = (target.definition() for target in targets)
    return [record for record in found if record is not None]
