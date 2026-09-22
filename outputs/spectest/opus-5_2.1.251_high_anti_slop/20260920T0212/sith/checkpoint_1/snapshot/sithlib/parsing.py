"""Parsing that tolerates the broken code an editor sees mid-keystroke."""

import ast

_MAX_REPAIRS = 50


def parse_tolerant(source):
    """Parse `source`, blanking the lines Python rejects until the rest parses."""
    lines = source.splitlines(keepends=True)
    for _ in range(_MAX_REPAIRS):
        try:
            return ast.parse("".join(lines))
        except SyntaxError as error:
            index = _culprit(lines, error)
            if index is None:
                break
            lines[index] = "\n"
    return ast.parse("")


def _culprit(lines, error):
    """Index of the line to blank out, walking back over already blank ones."""
    index = min((error.lineno or len(lines)) - 1, len(lines) - 1)
    while index >= 0 and not lines[index].strip():
        index -= 1
    return index if index >= 0 else None
