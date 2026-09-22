"""Evaluation of XPath 1.0 queries."""

from lxml import etree

from .errors import CssSelectorError, XPathQueryError

# lxml's xpath() implements XPath 1.0, so no version selection is needed.
XPathResult = list | float | bool | str


def evaluate(document: etree._Element, query: str, selector: str | None = None):
    """Evaluate `query` against `document`.

    Returns whatever XPath 1.0 object the expression produces: a node set as a
    list, or a number, boolean or string. `selector` is the CSS selector
    `query` was translated from, if any, so that a failure in CSS mode is
    reported against what the user actually wrote.
    """
    try:
        return document.xpath(query)
    except etree.XPathError as exc:
        if selector is not None:
            raise CssSelectorError(f"invalid css selector {selector!r}: {exc}") from exc
        raise XPathQueryError(f"invalid xpath expression {query!r}: {exc}") from exc
