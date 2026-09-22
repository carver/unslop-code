"""Evaluation of XPath expressions against a parsed document."""

from lxml import etree

from .errors import XjqError

XPathResult = list | str | float | bool

_QUOTES = "\"'"
_OPENING = "(["
_CLOSING = ")]"


def evaluate(root: etree._Element, expression: str) -> XPathResult:
    """Evaluate the XPath 1.0 ``expression`` against ``root``.

    Returns a list for node-sets, or a string/number/boolean for expressions
    such as ``string(//a)`` or ``count(//a)``. A ``|`` union yields the nodes of
    all of its sub-paths, in document order and without duplicates.

    Raises:
        XjqError: the expression is not valid XPath 1.0.
    """
    try:
        return root.xpath(expression)
    except etree.XPathError as exc:
        raise XjqError(f"error: invalid xpath expression {expression!r}: {exc}") from exc


def is_union(expression: str) -> bool:
    """Tell whether ``expression`` joins several paths with a top-level ``|``.

    A ``|`` inside a string literal, a predicate or a function call belongs to a
    single path and does not make the expression a union.
    """
    quote = ""
    depth = 0
    for char in expression:
        if quote:
            quote = "" if char == quote else quote
        elif char in _QUOTES:
            quote = char
        elif char in _OPENING:
            depth += 1
        elif char in _CLOSING:
            depth -= 1
        elif char == "|" and depth == 0:
            return True
    return False
