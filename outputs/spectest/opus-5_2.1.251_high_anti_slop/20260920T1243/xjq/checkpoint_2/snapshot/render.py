"""Rendering of XPath results into the text written to stdout."""

import math
import re

from lxml import etree

_WHITESPACE_RUN = re.compile(r"\s+")


def render(result):
    """Return the stdout text for an XPath result, empty when nothing matched.

    Node sets holding elements are serialized as pretty-printed XML, and only
    the first such node is rendered. Everything else is rendered as text: one
    stripped, whitespace-collapsed value per line.
    """
    if not isinstance(result, list):
        return _as_line(_render_scalar(result))
    if not result:
        return ""
    if etree.iselement(result[0]):
        return etree.tostring(
            result[0], pretty_print=True, with_tail=False, encoding="unicode"
        )
    return "".join(_as_line(_collapse(value)) for value in result)


def _render_scalar(value):
    """Render a boolean, number or string XPath result the way XPath 1.0 does."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _format_number(value)
    return _collapse(value)


def _format_number(value):
    """Format a number as XPath 1.0 string() does: 15 significant digits."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return f"{value:.15g}"


def _collapse(text):
    """Strip `text` and collapse every internal run of whitespace to one space."""
    return _WHITESPACE_RUN.sub(" ", text).strip()


def _as_line(text):
    """Terminate a rendered value with a newline, dropping it when it is empty."""
    return f"{text}\n" if text else ""
