"""Evaluation of XPath 1.0 queries."""

from lxml import etree

from .errors import XPathQueryError

# lxml's xpath() implements XPath 1.0, so no version selection is needed.
XPathResult = list | float | bool | str


def evaluate(document: etree._Element, query: str) -> XPathResult:
    """Evaluate `query` against `document`.

    Returns whatever XPath 1.0 object the expression produces: a node set as a
    list, or a number, boolean or string.
    """
    try:
        return document.xpath(query)
    except etree.XPathError as exc:
        raise XPathQueryError(f"invalid xpath expression {query!r}: {exc}") from exc
