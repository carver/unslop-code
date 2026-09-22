"""Evaluation of XPath 1.0 expressions against a parsed document."""

from lxml import etree

from errors import XPathError

_QUOTES = "'\""
_OPENING = "(["
_CLOSING = ")]"
_UNION = "|"


def evaluate(document, expression: str):
    """Evaluate ``expression`` against ``document``.

    Returns whatever XPath 1.0 yields: a list of nodes or strings, or a
    single boolean, number or string. A union of sub-paths yields their
    matches together, in document order.

    Raises:
        XPathError: if the expression is malformed or cannot be evaluated.
    """
    try:
        return document.xpath(expression)
    except etree.XPathError as exc:
        raise XPathError(f"xpath error: {exc}") from exc


def is_union(expression: str) -> bool:
    """Report whether ``expression`` joins several sub-paths with ``|``.

    Only a ``|`` that separates the sub-paths of the query itself counts; one
    inside a string literal, a predicate or a parenthesized sub-expression
    belongs to that sub-expression.
    """
    quote = None
    depth = 0
    for char in expression:
        if quote is not None:
            quote = None if char == quote else quote
        elif char in _QUOTES:
            quote = char
        elif char in _OPENING:
            depth += 1
        elif char in _CLOSING:
            depth -= 1
        elif char == _UNION and depth == 0:
            return True
    return False
