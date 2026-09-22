"""Spelling a symbol anew wherever the project writes it.

The places to change are the ones ``references --scope project`` reports: every
occurrence that leads back to the definitions the cursor's name leads to, and
nothing that merely shares its spelling.
"""

from __future__ import annotations

from .cursor import Reference
from .definitions import Definition
from .edits import Edit, Refactoring, collect
from .errors import SithError
from .project import Analysis, Project
from .references import Occurrence, matching, resolve
from .scopes import Scope
from .trees import Span


def rename(project: Project, reference: Reference, scope: Scope, line: int,
           new_name: str) -> Refactoring:
    """Rename the symbol under the cursor, and every reference to it."""
    target = frozenset(resolve(reference, scope, line, follow=True))
    analyses = project.analyses()
    found = [occurrence for analysis in analyses.values()
             for occurrence, _ in matching(analysis, reference.name, target)]
    _reject_collisions(analyses, found, new_name, target)
    return collect(occurrence_edits(found, len(reference.name), new_name),
                   {path: analysis.info.text for path, analysis in analyses.items()})


def occurrence_edits(occurrences: list[Occurrence], length: int,
                     new_name: str) -> list[Edit]:
    """One edit per occurrence, replacing the name written there."""
    return [Edit(occurrence.module_path,
                 Span(occurrence.line, occurrence.column,
                      occurrence.line, occurrence.column + length),
                 new_name)
            for occurrence in occurrences]


def _reject_collisions(analyses: dict[str, Analysis], occurrences: list[Occurrence],
                       new_name: str, target: frozenset[Definition]) -> None:
    """Refuse a new name that something else already answers to.

    A name is in the way when it is bound where one of the occurrences is
    written: the renamed symbol would be shadowed by it, or shadow it.
    """
    for occurrence in occurrences:
        scope = analyses[occurrence.module_path].module.scope.innermost(occurrence.line)
        for binding in scope.lookup(new_name, occurrence.line):
            if binding.definition() not in target:
                raise SithError(
                    f"cannot rename to '{new_name}': the name is already defined at "
                    f"{binding.site.module_path}:{binding.site.line}")
