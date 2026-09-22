"""Parsing that tolerates the broken code an editor sees mid-keystroke."""

import ast

_MAX_REPAIRS = 50


def parse_tolerant(source):
    """Parse `source`, replacing the lines Python rejects until the rest parses.

    A rejected line becomes ``pass`` when it is the body of the block above it,
    so that the block itself survives, and a blank line otherwise.
    """
    lines = source.splitlines(keepends=True)
    repaired = set()
    for _ in range(_MAX_REPAIRS):
        try:
            return ast.parse("".join(lines))
        except SyntaxError as error:
            index = _culprit(lines, error, repaired)
            if index is None:
                break
            lines[index] = _replacement(lines, index)
            repaired.add(index)
    return ast.parse("")


def _culprit(lines, error, repaired):
    """Index of the line to replace, walking back over blank and repaired ones."""
    index = min((error.lineno or len(lines)) - 1, len(lines) - 1)
    while index >= 0 and (index in repaired or not lines[index].strip()):
        index -= 1
    return index if index >= 0 else None


def _replacement(lines, index):
    text = lines[index]
    if not _follows_header(lines, index):
        return "\n"
    indent = text[: len(text) - len(text.lstrip())]
    return f"{indent}pass\n"


def _follows_header(lines, index):
    """Whether the nearest statement above the line opens a block."""
    for text in reversed(lines[:index]):
        if text.strip():
            return text.rstrip().endswith(":")
    return False
