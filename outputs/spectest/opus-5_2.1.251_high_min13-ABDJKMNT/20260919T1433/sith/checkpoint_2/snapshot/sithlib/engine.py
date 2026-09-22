"""Turning a cursor position into completion results."""

from __future__ import annotations

import ast
import keyword
from typing import Dict, List, Optional

from .analysis import Analyzer, merged
from .context import ATTRIBUTE, Context, context_at
from .narrowing import narrowed_lookup
from .results import payload
from .source import Source
from .symbols import KEYWORD, Symbol


def complete(source: Source, line: int, col: int, fuzzy: bool) -> str:
    """Completions for a position in a source file, as a JSON document."""
    context = context_at(source.line_at(line, col), col)
    analyzer = Analyzer(source)
    visible = analyzer.visible(line, context.indent)
    lookup = narrowed_lookup(analyzer, visible, line, context.indent)
    if context.kind == ATTRIBUTE:
        candidates = attribute_candidates(analyzer, context, lookup)
    else:
        candidates = [merged(group) for group in visible.values()] + keyword_candidates(visible)
    return payload(candidates, context.prefix, fuzzy)


def attribute_candidates(analyzer: Analyzer, context: Context, lookup) -> List[Symbol]:
    """Members of the expression written before the dot."""
    expression = parse_expression(context.receiver)
    if expression is None:
        return []
    value = analyzer.resolve(expression, lookup)
    return value.members() if value is not None else []


def keyword_candidates(taken: Dict[str, List[Symbol]]) -> List[Symbol]:
    """Python keywords, minus those already offered as names."""
    return [Symbol(word, KEYWORD) for word in keyword.kwlist if word not in taken]


def parse_expression(text: str) -> Optional[ast.expr]:
    """Parse the receiver written before a dot, if it is an expression."""
    try:
        return ast.parse(text.strip(), mode="eval").body
    except SyntaxError:
        return None
