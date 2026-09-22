"""Rendering of XPath results into the text written to stdout."""

import re

from lxml import etree

_WHITESPACE_RUN = re.compile(r"\s+")


def render(result) -> str:
    """Return the stdout text for ``result``, without a trailing newline.

    Element results are pretty-printed, and only the first one is shown. Text
    and attribute results are normalized and joined one per line. Anything
    else is a scalar produced by a function such as ``count()``.
    """
    if not isinstance(result, list):
        return _render_scalar(result)
    if not result:
        return ""
    if etree.iselement(result[0]):
        return etree.tostring(
            result[0], pretty_print=True, with_tail=False, encoding="unicode"
        ).rstrip("\n")
    return "\n".join(_normalize(str(item)) for item in result)


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
