"""Evaluation of XPath expressions against a parsed document."""

from lxml import etree

from .errors import XjqError

XPathResult = list | str | float | bool


def evaluate(root: etree._Element, expression: str) -> XPathResult:
    """Evaluate the XPath 1.0 ``expression`` against ``root``.

    Returns a list for node-sets, or a string/number/boolean for expressions
    such as ``string(//a)`` or ``count(//a)``.

    Raises:
        XjqError: the expression is not valid XPath 1.0.
    """
    try:
        return root.xpath(expression)
    except etree.XPathError as exc:
        raise XjqError(f"error: invalid xpath expression {expression!r}: {exc}") from exc
