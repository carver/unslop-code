"""Evaluation of XPath 1.0 expressions against a parsed document."""

from lxml import etree

from .errors import XjqError


def evaluate(document: etree._Element, query: str):
    """Evaluate ``query`` against ``document``.

    Returns whatever the XPath data model yields: a list of nodes and/or
    strings, or a string, number, or boolean. Raises :class:`XjqError` when the
    expression is not valid XPath 1.0 for this document.
    """
    try:
        return document.xpath(query)
    except etree.XPathError as error:
        raise XjqError(f"invalid xpath expression {query!r}: {error}") from error
