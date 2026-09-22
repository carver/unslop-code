"""Evaluation of an XPath 1.0 expression against a parsed document."""

from lxml import etree

from .errors import XPathQueryError


def evaluate(root, expression):
    """Evaluate `expression` against `root` and return lxml's raw result.

    The result is either a list of nodes (elements, comments, processing
    instructions, and the string-like objects lxml yields for `text()` and
    attribute steps) or a scalar for expressions such as `count(...)`.
    Anything lxml rejects — bad syntax, an unknown function, an unbound
    namespace prefix — surfaces as `XPathQueryError`.
    """
    try:
        return root.xpath(expression)
    except etree.XPathError as exc:
        raise XPathQueryError(exc) from exc
