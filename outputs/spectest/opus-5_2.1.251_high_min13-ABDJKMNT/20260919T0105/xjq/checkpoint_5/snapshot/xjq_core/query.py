"""Evaluation of an XPath 1.0 expression against a parsed document."""

from lxml import etree

from .errors import XPathQueryError


def evaluate(root, expression, failure=XPathQueryError):
    """Evaluate `expression` against `root` and return lxml's raw result.

    The result is either a list of nodes (elements, comments, processing
    instructions, and the string-like objects lxml yields for `text()` and
    attribute steps) or a scalar for expressions such as `count(...)`.
    Anything lxml rejects — bad syntax, an unknown function, an unbound
    namespace prefix — surfaces as `failure`. A CSS query passes
    `CssSelectorError` for it: the expression being evaluated is the one the
    translation produced, not one the user could look at. `a|b`, which CSS
    reads as a namespace rather than a union, arrives here.
    """
    try:
        return root.xpath(expression)
    except etree.XPathError as exc:
        raise failure(exc) from exc
