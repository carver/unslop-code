"""The call the cursor sits in, and which parameter its argument binds to.

Signature help is wanted while a call is still being typed, when the file
does not parse; the call around the cursor is therefore read from the text
itself, tracking strings, comments and brackets rather than statements.
"""

import inspect
import re
from dataclasses import dataclass, field

from .source import line_at, trailing_expression

Kind = inspect.Parameter
POSITIONAL = (Kind.POSITIONAL_ONLY, Kind.POSITIONAL_OR_KEYWORD)
NAMED = (Kind.POSITIONAL_OR_KEYWORD, Kind.KEYWORD_ONLY)

_OPENING = "([{"
_CLOSING = ")]}"
_TRIPLES = ("'''", '"""')
_DEFINING = re.compile(r"\b(?:def|class)\s+[A-Za-z_]\w*\s*$")
_KEYWORD_ARGUMENT = re.compile(r"^\s*([A-Za-z_]\w*)\s*=(?!=)")


@dataclass(frozen=True)
class Parameter:
    """One declared parameter: its name, how it is written, and how it binds."""

    name: str
    text: str
    kind: object


@dataclass(frozen=True)
class Call:
    """A call whose argument list is still open at the cursor.

    `callee` is the expression being called, and `arguments` the text of each
    argument typed so far, the last one ending at the cursor.
    """

    callee: object
    arguments: list


def call_at(lines, line, column):
    """The call whose argument list holds the cursor, or ``None`` outside one."""
    text = "\n".join(list(lines[: line - 1]) + [line_at(lines, line, column)[:column]])
    for frame in reversed(_open_frames(text)):
        callee = _callee(text[: frame.start]) if frame.opening == "(" else None
        if callee is not None:
            return Call(callee, _arguments(text, frame))
    return None


def parameter_index(parameters, arguments):
    """Which parameter the last argument binds to, as a call would bind it."""
    named = _KEYWORD_ARGUMENT.match(arguments[-1])
    if named is not None:
        return _by_name(parameters, named.group(1))
    position = sum(1 for argument in arguments[:-1] if not _KEYWORD_ARGUMENT.match(argument))
    return _by_position(parameters, position)


@dataclass
class _Frame:
    """An unclosed bracket and the commas typed directly inside it."""

    opening: str
    start: int
    commas: list = field(default_factory=list)


def _open_frames(text):
    """The brackets still open at the end of `text`, outermost first."""
    frames = []
    index = 0
    while index < len(text):
        character = text[index]
        if character in "\"'":
            index = _string_end(text, index)
        elif character == "#":
            found = text.find("\n", index)
            index = len(text) if found < 0 else found
        else:
            _track(frames, character, index)
            index += 1
    return frames


def _track(frames, character, index):
    """Record what one character does to the brackets open around the cursor."""
    if character in _OPENING:
        frames.append(_Frame(character, index))
    elif character in _CLOSING and frames:
        frames.pop()
    elif character == "," and frames:
        frames[-1].commas.append(index)


def _string_end(text, start):
    """The index just past the string literal starting at `start`."""
    quote = text[start:start + 3] if text.startswith(_TRIPLES, start) else text[start]
    index = start + len(quote)
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text.startswith(quote, index):
            return index + len(quote)
        else:
            index += 1
    return len(text)


def _arguments(text, frame):
    """The text of each argument typed inside a bracket, split at its commas."""
    starts = [frame.start] + frame.commas
    ends = frame.commas + [len(text)]
    return [text[start + 1:end] for start, end in zip(starts, ends)]


def _callee(head):
    """The expression the text before an open bracket calls, if it calls one.

    A bracket is a call when an expression stands in front of it; the one
    opening a parameter list stands behind a name being defined instead.
    """
    return None if _DEFINING.search(head) else trailing_expression(head)


def _by_name(parameters, name):
    """The parameter a keyword argument names, else the one collecting the rest."""
    found = next((index for index, parameter in enumerate(parameters)
                  if parameter.name == name and parameter.kind in NAMED), None)
    return found if found is not None else _of_kind(parameters, Kind.VAR_KEYWORD)


def _by_position(parameters, position):
    """The parameter at a position, else the one collecting extra arguments."""
    slots = [index for index, parameter in enumerate(parameters)
             if parameter.kind in POSITIONAL]
    if position < len(slots):
        return slots[position]
    return _of_kind(parameters, Kind.VAR_POSITIONAL)


def _of_kind(parameters, kind):
    return next((index for index, parameter in enumerate(parameters)
                 if parameter.kind == kind), None)
