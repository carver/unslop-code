"""Turning a cursor position into completion results."""

from __future__ import annotations

import keyword
from typing import Callable, Dict, List

from .analysis import Analyzer, merged
from .context import (
    ATTRIBUTE,
    IMPORT_NAME,
    MODULE_PATH,
    NAME,
    Context,
    context_at,
    parse_expression,
)
from .importing import written_path
from .narrowing import narrowed_lookup
from .project import Project
from .results import payload
from .source import Source
from .symbols import KEYWORD, Symbol


def complete(source: Source, project: Project, line: int, col: int, fuzzy: bool) -> str:
    """Completions for a position in a source file, as a JSON document."""
    context = context_at(source.line_at(line, col), col)
    analyzer = project.analyzer_for(source)
    candidates = CANDIDATES[context.kind](analyzer, context, line)
    return payload(candidates, context.prefix, fuzzy, project.settings)


def _name_candidates(analyzer: Analyzer, context: Context, line: int) -> List[Symbol]:
    """Every name in scope at the cursor, the keywords none of them took, and
    the names only a running interpreter knows about."""
    visible = analyzer.visible(line, context.indent)
    found = [merged(group) for group in visible.values()] + _keyword_candidates(visible)
    return found + analyzer.project.namespaces.absent_from(visible)


def _attribute_candidates(analyzer: Analyzer, context: Context, line: int) -> List[Symbol]:
    """Members of the expression written before the dot."""
    expression = parse_expression(context.receiver)
    if expression is None:
        return []
    value = analyzer.resolve(expression, _lookup_at(analyzer, context, line))
    if value is None:
        value = analyzer.project.namespaces.value_of(expression)
    return value.members() if value is not None else []


def _module_candidates(analyzer: Analyzer, context: Context, line: int) -> List[Symbol]:
    """Modules that can be named at this point of an import path."""
    return analyzer.project.module_names(analyzer, context.module)


def _import_candidates(analyzer: Analyzer, context: Context, line: int) -> List[Symbol]:
    """Names a `from ... import` clause can take out of its module."""
    level, dotted = written_path(context.module)
    module = analyzer.project.module_for(analyzer, level, dotted)
    return module.members() if module is not None else []


CANDIDATES: Dict[str, Callable[[Analyzer, Context, int], List[Symbol]]] = {
    NAME: _name_candidates,
    ATTRIBUTE: _attribute_candidates,
    MODULE_PATH: _module_candidates,
    IMPORT_NAME: _import_candidates,
}


def _lookup_at(analyzer: Analyzer, context: Context, line: int):
    """Name lookup as the cursor sees it, narrowed by the branch it sits in."""
    visible = analyzer.visible(line, context.indent)
    return narrowed_lookup(analyzer, visible, line, context.indent)


def _keyword_candidates(taken: Dict[str, List[Symbol]]) -> List[Symbol]:
    """Python keywords, minus those already offered as names."""
    return [Symbol(word, KEYWORD) for word in keyword.kwlist if word not in taken]
