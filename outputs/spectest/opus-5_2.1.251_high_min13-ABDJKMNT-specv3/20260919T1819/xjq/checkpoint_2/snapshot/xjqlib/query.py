"""Evaluation of XPath 1.0 expressions against a parsed document."""

from lxml import etree


class QueryError(Exception):
    """Raised when an expression is not valid XPath 1.0."""


def evaluate(root: etree._Element, query: str):
    """Return the XPath result: a node list, or a string, number or boolean."""
    try:
        return root.xpath(query)
    except etree.XPathError as exc:
        raise QueryError(str(exc)) from exc
