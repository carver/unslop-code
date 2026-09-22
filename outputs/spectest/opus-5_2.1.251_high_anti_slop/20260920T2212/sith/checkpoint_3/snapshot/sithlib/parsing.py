"""Syntax-error tolerant parsing.

Files are parsed while they are being edited, so a clean parse is the exception
rather than the rule.  Offending lines are neutralised in place -- never
removed -- so that every ``lineno`` in the resulting tree still points at the
line it came from in the original file.
"""

from __future__ import annotations

import ast


def tolerant_parse(text: str) -> ast.Module:
    """Parse ``text``, repairing broken lines until something parses."""
    lines = text.split("\n")
    attempts: dict[int, int] = {}
    while True:
        try:
            return ast.parse("\n".join(lines))
        except SyntaxError as error:
            index = min(max((error.lineno or len(lines)) - 1, 0), len(lines) - 1)
            attempt = attempts.get(index, 0)
            attempts[index] = attempt + 1
            _repair(lines, index, attempt)


def _repair(lines: list[str], index: int, attempt: int) -> None:
    """Escalate the repair applied to ``lines[index]`` on repeated failures."""
    match attempt:
        case 0:
            # Keep the line's block structure intact so the surrounding
            # ``def``/``if`` body does not become empty.
            lines[index] = _indent(lines[index]) + "pass"
        case 1:
            lines[index] = ""
        case _:
            # The damage starts here and continues; blank out the remainder.
            lines[index:] = [""] * (len(lines) - index)


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]
