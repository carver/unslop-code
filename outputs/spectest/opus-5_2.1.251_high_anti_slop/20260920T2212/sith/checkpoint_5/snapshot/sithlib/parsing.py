"""Syntax-error tolerant parsing.

Files are parsed while they are being edited, so a clean parse is the exception
rather than the rule.  Offending lines are neutralised in place -- never
removed -- so that every ``lineno`` in the resulting tree still points at the
line it came from in the original file.  What had to be neutralised is what the
``errors`` command reports.
"""

from __future__ import annotations

import ast


def tolerant_parse(text: str) -> ast.Module:
    """Parse ``text``, repairing broken lines until something parses."""
    return _repaired(text)[0]


def syntax_errors(text: str) -> list[SyntaxError]:
    """The lines of ``text`` the parser rejected, one error per broken line.

    Repairing a line makes the parser reach the next problem, so a file with
    several broken lines reports several errors; the escalating repairs of one
    line report only what the parser said the first time it was reached.
    """
    return _repaired(text)[1]


def _repaired(text: str) -> tuple[ast.Module, list[SyntaxError]]:
    lines = text.split("\n")
    attempts: dict[int, int] = {}
    reported: list[SyntaxError] = []
    while True:
        try:
            return ast.parse("\n".join(lines)), reported
        except SyntaxError as error:
            index = min(max((error.lineno or len(lines)) - 1, 0), len(lines) - 1)
            attempt = attempts.get(index, 0)
            if not attempt:
                reported.append(error)
            attempts[index] = attempt + 1
            _repair(lines, index, attempt)


def _repair(lines: list[str], index: int, attempt: int) -> None:
    """Escalate the repair applied to ``lines[index]`` on repeated failures."""
    match attempt:
        case 0:
            # Keep the line's block structure intact so the surrounding
            # ``def``/``if`` body does not become empty, and take with it the
            # block the line introduced, which has just lost its header.
            _blank_block(lines, index)
            lines[index] = _indent(lines[index]) + "pass"
        case 1:
            lines[index] = ""
        case _:
            # The damage starts here and continues; blank out the remainder.
            lines[index:] = [""] * (len(lines) - index)


def _blank_block(lines: list[str], index: int) -> None:
    """Empty whatever was written under ``lines[index]``, deeper than it."""
    depth = len(_indent(lines[index]))
    for following in range(index + 1, len(lines)):
        if lines[following].strip() and len(_indent(lines[following])) <= depth:
            return
        lines[following] = ""


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]
