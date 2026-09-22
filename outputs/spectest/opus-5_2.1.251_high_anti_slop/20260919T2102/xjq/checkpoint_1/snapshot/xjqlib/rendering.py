"""Formatting of XPath results into the text written to stdout."""

import re

from lxml import etree

from .query import XPathResult

_WHITESPACE_RUN = re.compile(r"\s+")


def render(result: XPathResult) -> str:
    """Render an XPath result as the output of a query.

    Element results are pretty-printed XML, limited to the first match; every
    other kind of result is whitespace-normalized, one match per line.
    """
    if not isinstance(result, list):
        return _normalize(_scalar_to_text(result))
    elements = [item for item in result if isinstance(item, etree._Element)]
    if elements:
        return serialize(elements[0])
    return "\n".join(_normalize(str(item)) for item in result)


def serialize(element: etree._Element) -> str:
    """Pretty-print a single element as indented XML."""
    return etree.tostring(element, pretty_print=True, encoding="unicode").rstrip("\n")


def _scalar_to_text(value: str | float | bool) -> str:
    """Convert an XPath boolean/number/string result to its XPath 1.0 lexical form."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _normalize(text: str) -> str:
    """Strip the text and collapse internal whitespace runs to single spaces."""
    return _WHITESPACE_RUN.sub(" ", text).strip()
