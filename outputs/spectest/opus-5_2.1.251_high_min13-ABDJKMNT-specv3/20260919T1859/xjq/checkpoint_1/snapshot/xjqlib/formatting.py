"""Rendering an XPath result as the payload written to stdout."""

import math
import re

from lxml import etree

_WHITESPACE_RUN = re.compile(r"\s+")


def format_result(result) -> str:
    """Render an XPath result for stdout.

    A node-set holding element (or comment/processing-instruction) nodes is
    rendered as the pretty-printed serialization of its first node. Anything
    else -- attribute and text hits, and scalar results -- is rendered as
    stripped, whitespace-collapsed lines. An empty result renders as an empty
    payload, so nothing is written at all.
    """
    if isinstance(result, list):
        return _format_node_set(result)
    return _collapse(_scalar_to_string(result))


def _format_node_set(nodes) -> str:
    """Render a node-set, preferring XML serialization when nodes are present."""
    elements = [node for node in nodes if isinstance(node, etree._Element)]
    if elements:
        return _serialize(elements[0])
    return "\n".join(_collapse(str(node)) for node in nodes)


def _serialize(element: etree._Element) -> str:
    """Pretty-print one node, excluding the text that trails its closing tag."""
    xml = etree.tostring(
        element, pretty_print=True, with_tail=False, encoding="unicode"
    )
    return xml.rstrip("\n") + "\n"


def _collapse(text: str) -> str:
    """Strip the ends of ``text`` and squeeze internal whitespace to one space."""
    return _WHITESPACE_RUN.sub(" ", text.strip())


def _scalar_to_string(value) -> str:
    """Convert a non-node-set result using XPath 1.0 string conversion."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _number_to_string(value)
    return str(value)


def _number_to_string(number: float) -> str:
    """Format a number the way XPath 1.0 does: ``2`` rather than ``2.0``."""
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "Infinity" if number > 0 else "-Infinity"
    if number.is_integer():
        return str(int(number))
    return repr(number)
