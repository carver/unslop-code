"""Splitting a query on the separators that are not nested inside it."""

_NESTING = {"(": ")", "[": "]"}


def split_top_level(text: str, separator: str) -> list[str]:
    """Split ``text`` on each ``separator`` outside quotes, brackets and parens.

    A separator inside a predicate, an argument list or a string literal -- as
    in ``:not(a, b)``, ``[title=","]`` or ``//a[@id='x|y']`` -- belongs to the
    query around it rather than breaking it in two.
    """
    parts, current, closers, quote = [], [], [], ""
    for char in text:
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char in _NESTING:
            closers.append(_NESTING[char])
        elif closers and char == closers[-1]:
            closers.pop()
        elif char == separator and not closers:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts
