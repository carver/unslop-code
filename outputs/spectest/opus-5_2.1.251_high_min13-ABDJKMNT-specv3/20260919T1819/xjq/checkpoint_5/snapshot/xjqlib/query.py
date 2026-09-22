"""Evaluation of XPath 1.0 expressions against a parsed document."""

from lxml import etree

from xjqlib.scan import split_top_level

#: The XPath union operator, which joins several paths into one result.
UNION = "|"


class QueryError(Exception):
    """Raised when an expression is not valid XPath 1.0."""


def evaluate(root: etree._Element, query: str):
    """Return the XPath result: a node list, or a string, number or boolean."""
    try:
        return root.xpath(query)
    except etree.XPathError as exc:
        raise QueryError(str(exc)) from exc


def is_union(query: str) -> bool:
    """Whether ``query`` joins two or more paths with a top-level ``|``."""
    return len(split_top_level(query, UNION)) > 1
