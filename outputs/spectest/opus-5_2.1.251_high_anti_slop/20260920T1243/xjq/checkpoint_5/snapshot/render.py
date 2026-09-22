"""Rendering of XPath results into the text written to stdout."""

import math

from lxml import etree

from textnodes import normalize


def render(result, first=False, compact=False):
    """Return the stdout text for an XPath result, empty when nothing matched.

    Elements of a node set are serialized as XML, pretty-printed unless
    `compact` asks for the serializer's own formatting; every other value is
    rendered as text, one stripped and whitespace-collapsed value per line.
    With `first`, only the first value of a node set is rendered, whichever of
    the two forms it takes; the other XPath types are single values already.
    """
    if not isinstance(result, list):
        return line(_render_scalar(result))
    values = result[:1] if first else result
    return "".join(_render_node(value, compact) for value in values)


def line(text):
    """Terminate a rendered value with a newline, dropping it when it is empty."""
    return f"{text}\n" if text else ""


def _render_node(value, compact):
    """Render one entry of a node set: an element as XML, its text as a line."""
    if etree.iselement(value):
        return line(_serialize(value, compact))
    return line(normalize(value))


def _serialize(element, compact):
    """Serialize one matched element as XML occupying whole lines of output."""
    xml = etree.tostring(
        element, pretty_print=not compact, with_tail=False, encoding="unicode"
    )
    return xml.rstrip("\n")


def _render_scalar(value):
    """Render a boolean, number or string XPath result the way XPath 1.0 does."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _format_number(value)
    return normalize(value)


def _format_number(value):
    """Format a number as XPath 1.0 string() does: 15 significant digits."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return f"{value:.15g}"
