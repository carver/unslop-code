"""What the refactoring commands have in common: a cursor, a name, a workspace."""

from __future__ import annotations

import keyword

from . import cursor
from .analysis import Analysis
from .options import DEFAULT, Options
from .source import SithError


def identifier(name: str) -> str:
    """The new name a refactoring was given, refused unless it could be written."""
    if not name.isidentifier() or keyword.iskeyword(name):
        raise SithError(f"not a valid Python identifier: {name}")
    return name


def at_cursor(path: str, line: int, col: int, root: str,
              options: Options = DEFAULT) -> tuple[Analysis, cursor.Reference]:
    """The file under the cursor and the name the cursor rests on.

    Imports are followed, so that a cursor on an imported name is understood
    to be on the thing it was imported from.
    """
    analysis = Analysis.at(path, line, col, root, follow=True, options=options)
    reference = cursor.reference_at(analysis.line_text, col)
    if reference is None or reference.name is None:
        raise SithError(f"no name at line {line}, column {col}")
    return analysis, reference
