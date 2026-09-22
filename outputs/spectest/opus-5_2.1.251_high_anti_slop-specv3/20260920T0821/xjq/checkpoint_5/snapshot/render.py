"""Turning XPath results into the text written to stdout."""

from lxml import etree

from query import Result
from text import TextMode, node_text, normalize


def render(result: Result, first: bool = False, compact: bool = False) -> str:
    """Return the stdout text for ``result``, without a trailing newline.

    A result made up entirely of elements is serialized as XML — pretty-printed,
    or without any added formatting when ``compact``. Because a serialized
    element can span several lines, only the first matching element is printed.
    Every other kind of result, including a union that matched both elements and
    text, is rendered as whitespace-normalized text, one match per line.

    ``first`` keeps only the first of the matches, whichever kind they are, and
    so prints nothing at all when there are none.
    """
    if not isinstance(result, list):
        return normalize(_scalar_text(result))
    if first:
        result = result[:1]
    if result and all(isinstance(node, etree._Element) for node in result):
        return etree.tostring(
            result[0], pretty_print=not compact, with_tail=False, encoding="unicode"
        ).strip()
    return "\n".join(normalize(_text(node)) for node in result)


def _text(node: etree._Element | str) -> str:
    """Return the text of one node in a result that is written out as text."""
    if isinstance(node, etree._Element):
        return node_text(node, TextMode.DESCENDANT)
    return str(node)


def _scalar_text(value: bool | float | str) -> str:
    """Render a boolean, number or string result the way XPath 1.0 spells it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
