"""Turning XPath results into the text written to stdout."""

import re

from lxml import etree

from query import Result

_WHITESPACE_RUN = re.compile(r"\s+")


def render(result: Result, first: bool = False, compact: bool = False) -> str:
    """Return the stdout text for ``result``, without a trailing newline.

    Element results are serialized as XML — pretty-printed, or without any
    added formatting when ``compact``. Because a serialized element can span
    several lines, only the first matching element is printed. Every other kind
    of result is rendered as whitespace-normalized text, one match per line.

    ``first`` keeps only the first of the matches, whichever kind they are, and
    so prints nothing at all when there are none.
    """
    if not isinstance(result, list):
        return _normalize(_scalar_text(result))
    if first:
        result = result[:1]
    elements = [node for node in result if isinstance(node, etree._Element)]
    if elements:
        return etree.tostring(
            elements[0], pretty_print=not compact, with_tail=False, encoding="unicode"
        ).strip()
    return "\n".join(_normalize(str(node)) for node in result)


def _scalar_text(value: bool | float | str) -> str:
    """Render a boolean, number or string result the way XPath 1.0 spells it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _normalize(text: str) -> str:
    """Strip ``text`` and collapse each run of internal whitespace to a space."""
    return _WHITESPACE_RUN.sub(" ", text.strip())
