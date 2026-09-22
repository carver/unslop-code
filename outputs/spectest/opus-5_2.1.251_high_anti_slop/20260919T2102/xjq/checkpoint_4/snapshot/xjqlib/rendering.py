"""Formatting of XPath results into the text written to stdout."""

import re

from lxml import etree

from .query import XPathResult

_WHITESPACE_RUN = re.compile(r"\s+")


def render(result: XPathResult, *, first: bool, compact: bool) -> str:
    """Render an XPath result as the output of a query.

    Element results are serialized XML, one element after the other; every other
    kind of result is whitespace-normalized, one match per line, leaving out the
    matches that hold no text at all. ``first`` keeps only the first element or
    line of the output and ``compact`` drops the indentation of the XML.
    """
    if not isinstance(result, list):
        return _normalize(_scalar_to_text(result))
    elements = [item for item in result if isinstance(item, etree._Element)]
    if elements:
        return "\n".join(serialize(element, compact) for element in _limit(elements, first))
    lines = [_normalize(str(item)) for item in result]
    return "\n".join(_limit([line for line in lines if line], first))


def serialize(element: etree._Element, compact: bool) -> str:
    """Serialize a single element as XML, indented unless ``compact`` is asked for."""
    return etree.tostring(element, pretty_print=not compact, encoding="unicode").rstrip("\n")


def _limit(items: list, first: bool) -> list:
    """Cut ``items`` down to its first entry when only the first result is wanted."""
    return items[:1] if first else items


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
