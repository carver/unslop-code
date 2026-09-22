"""Deciding what the cursor is in the middle of typing, or resting on."""

from __future__ import annotations

import keyword
import re
import tokenize
from dataclasses import dataclass

CLOSERS = {")": "(", "]": "[", "}": "{"}
OPENERS = {opener: closer for closer, opener in CLOSERS.items()}
SPACE = " \t"


@dataclass(frozen=True)
class CursorContext:
    """The partially typed prefix and, after a `.`, the receiver before it."""

    line: int
    col: int
    prefix: str
    receiver: str | None

    @property
    def is_attribute(self) -> bool:
        return self.receiver is not None


def analyze(line_text: str, line: int, col: int) -> CursorContext:
    """Split the text left of the cursor into a receiver and a typed prefix."""
    before = line_text[:col]
    prefix = before[_identifier_start(before, len(before)) :]
    head = before[: len(before) - len(prefix)].rstrip(SPACE)
    if not head.endswith("."):
        return CursorContext(line, col, prefix, None)
    return CursorContext(line, col, prefix, _atom_before(head[:-1]))


#: The shapes of a half-typed import statement, matched against the text left
#: of the cursor.  Each allows a dotted, possibly dot-prefixed module name.
FROM_IMPORT = re.compile(r"\s*from\s+(?P<module>[.\w]*)\s+import\s+(?P<names>.*)")
FROM = re.compile(r"\s*from\s+(?P<module>[.\w]*)")
IMPORT = re.compile(r"\s*import\s+(?P<names>.*)")
DOTTED = re.compile(r"[.\w]*")
ALIAS = re.compile(r"\bas\b")


@dataclass(frozen=True)
class ImportContext:
    """An import statement being typed at the cursor.

    `members` tells a `from X import <here>` apart from the module name of an
    `import <here>`.  `module` and `level` locate the module whose names are
    wanted: `level` is the number of leading dots of a relative import.
    """

    prefix: str
    module: str = ""
    level: int = 0
    members: bool = False


def import_at(line_text: str, col: int) -> ImportContext | None:
    """The import the cursor is inside, or None when it is not inside one."""
    before = line_text[:col]
    listed = FROM_IMPORT.fullmatch(before)
    if listed is not None:
        return _member_context(listed["module"], listed["names"])
    named = FROM.fullmatch(before)
    if named is not None:
        return _module_context(named["module"])
    imported = IMPORT.fullmatch(before)
    if imported is None:
        return None
    entry = _last_entry(imported["names"])
    return None if entry is None else _module_context(entry)


def _member_context(module: str, names: str) -> ImportContext | None:
    """`from X import a, b<here>`: a plain name inside an already-named module."""
    entry = _last_entry(names)
    if entry is None or "." in entry:
        return None
    level, dotted = _leading_dots(module)
    return ImportContext(entry, dotted, level, members=True)


def _module_context(text: str) -> ImportContext:
    """`import a.b<here>`: the last segment is the prefix, the rest is the package."""
    level, dotted = _leading_dots(text)
    package, _, prefix = dotted.rpartition(".")
    return ImportContext(prefix, package, level)


def _last_entry(names: str) -> str | None:
    """The entry being typed at the end of a comma-separated import list.

    An entry given an alias is the author's own word rather than a name to
    complete, and anything that is not a dotted name is not an import at all.
    """
    entry = names.rpartition(",")[2].lstrip(f"{SPACE}(")
    if ALIAS.search(entry) or not DOTTED.fullmatch(entry):
        return None
    return entry


def _leading_dots(text: str) -> tuple[int, str]:
    """A relative module name split into its dot count and the rest."""
    stripped = text.lstrip(".")
    return len(text) - len(stripped), stripped


@dataclass(frozen=True)
class Reference:
    """The expression the cursor rests on, and its trailing identifier.

    A literal has no identifier, so `name` is None and only `source` is set.
    `start` is the column the identifier begins at, which tells a definition
    the cursor rests on apart from a use of the same name elsewhere.
    """

    source: str
    name: str | None = None
    receiver: str | None = None
    start: int = 0


#: Keywords that are values in their own right, so a cursor may rest on them.
CONSTANTS = {"True", "False", "None"}


def reference_at(line_text: str, col: int) -> Reference | None:
    """What the cursor is resting on: a name, a literal, or nothing at all.

    Literals are looked for first, so that text inside a string is read as part
    of the string rather than as an identifier of its own.
    """
    literal = _literal_at(line_text, col)
    if literal is not None:
        return Reference(literal)
    start, end = _identifier_span(line_text, col)
    name = line_text[start:end]
    if name.isidentifier() and (name in CONSTANTS or not keyword.iskeyword(name)):
        return _named(line_text, start, name)
    return None


def _named(line_text: str, start: int, name: str) -> Reference:
    """A reference to `name`, carrying the receiver it hangs off when there is one."""
    head = line_text[:start].rstrip(SPACE)
    receiver = _atom_before(head[:-1]) if head.endswith(".") else None
    return Reference(f"{receiver}.{name}" if receiver else name, name, receiver, start)


def _identifier_span(text: str, col: int) -> tuple[int, int]:
    """The bounds of the identifier the cursor is inside or sits just after."""
    end = min(col, len(text))
    start = _identifier_start(text, end)
    while end < len(text) and _is_identifier_char(text[end]):
        end += 1
    return start, end


def _literal_at(text: str, col: int) -> str | None:
    """The source of the string or number literal the cursor rests on."""
    for token in _tokens(text):
        spans = token.start[1] <= col <= token.end[1]
        if spans and token.type in (tokenize.NUMBER, tokenize.STRING):
            return token.string
    return None


def _tokens(text: str) -> list[tokenize.TokenInfo]:
    """The tokens of one line, up to the point where it stops tokenizing."""
    found = []
    try:
        found.extend(tokenize.generate_tokens(iter([text]).__next__))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A line taken out of its block is routinely incomplete; whatever was
        # tokenized before the break is still usable.
        pass
    return found


def _is_identifier_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _identifier_start(text: str, end: int) -> int:
    while end > 0 and _is_identifier_char(text[end - 1]):
        end -= 1
    return end


def _atom_before(text: str) -> str | None:
    """The source of the expression ending at `text`, e.g. `a.b(c).d` or `'x'`."""
    end = len(text.rstrip(SPACE))
    stop = end
    while True:
        start = _atom_start(text, stop)
        if start is None:
            break
        stop = start
        dot = len(text[:stop].rstrip(SPACE)) - 1
        if dot < 0 or text[dot] != ".":
            break
        stop = dot
    return text[stop:end].strip() or None


def _atom_start(text: str, end: int) -> int | None:
    """Start index of the single atom ending at `end`, or None if there isn't one."""
    end = len(text[:end].rstrip(SPACE))
    if end == 0:
        return None
    char = text[end - 1]
    if char in CLOSERS:
        opener = _matching_opener(text, end)
        if opener is None:
            return None
        # A bracket may be a call or subscript hanging off a preceding atom.
        callee = _atom_start(text, opener)
        return opener if callee is None else callee
    if char in "\"'":
        return _string_start(text, end)
    if _is_identifier_char(char):
        return _identifier_start(text, end)
    return None


def _matching_opener(text: str, end: int) -> int | None:
    depth = 0
    for index in range(end - 1, -1, -1):
        char = text[index]
        if char in CLOSERS:
            depth += 1
        elif char in OPENERS:
            depth -= 1
            if depth == 0:
                return index
    return None


def _string_start(text: str, end: int) -> int | None:
    quote = text[end - 1]
    index = text.rfind(quote, 0, end - 1)
    return index if index >= 0 else None
