"""Rendering of XPath results into the text written to stdout."""

import re

from lxml import etree

_WHITESPACE_RUN = re.compile(r"\s+")


def render(result, first: bool = False, compact: bool = False) -> str:
    """Return the stdout text for ``result``, without a trailing newline.

    Element results are serialized, and only the first one is shown with or
    without ``first``. Text and attribute results are normalized and joined one
    per line, or cut to their first entry under ``first``. Anything else is a
    scalar produced by a function such as ``count()``, which is one result
    already.
    """
    if not isinstance(result, list):
        return _render_scalar(result)
    if not result:
        return ""
    if etree.iselement(result[0]):
        return _render_element(result[0], compact)
    items = result[:1] if first else result
    return "\n".join(_normalize(str(item)) for item in items)


def _render_element(element, compact: bool) -> str:
    """Serialize an element, pretty-printed unless compact output was asked for.

    Compact output adds no indentation of its own, and the source indentation
    was already dropped at parse time, so the element serializes on one line.
    """
    return etree.tostring(
        element, pretty_print=not compact, with_tail=False, encoding="unicode"
    ).rstrip("\n")


def _render_scalar(value) -> str:
    """Format a non node-set result the way XPath 1.0 ``string()`` would."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _normalize(str(value))


def _normalize(text: str) -> str:
    """Strip ``text`` and collapse its internal whitespace runs to spaces."""
    return _WHITESPACE_RUN.sub(" ", text.strip())
