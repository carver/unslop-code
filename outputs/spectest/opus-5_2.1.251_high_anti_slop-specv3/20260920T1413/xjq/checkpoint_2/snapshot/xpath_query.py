"""Evaluation of XPath 1.0 expressions against a parsed document."""

from lxml import etree

from errors import XPathError


def evaluate(document, expression: str):
    """Evaluate ``expression`` against ``document``.

    Returns whatever XPath 1.0 yields: a list of nodes or strings, or a
    single boolean, number or string.

    Raises:
        XPathError: if the expression is malformed or cannot be evaluated.
    """
    try:
        return document.xpath(expression)
    except etree.XPathError as exc:
        raise XPathError(f"xpath error: {exc}") from exc
