"""Rendering a query result as the payload written to stdout."""

import copy
import math
import re
from dataclasses import dataclass

from lxml import etree

from .text import TextMode, extract_text

_WHITESPACE_RUN = re.compile(r"\s+")


@dataclass(frozen=True)
class OutputOptions:
    """The output flags: keep only the first result, and skip pretty-printing."""

    first: bool = False
    compact: bool = False


def format_result(
    result,
    extraction: TextMode | None = None,
    options: OutputOptions = OutputOptions(),
) -> str:
    """Render a query result for stdout.

    Without an extraction mode, a node-set holding element (or comment /
    processing-instruction) nodes is rendered as the serialization of its first
    node. With one, those nodes contribute their text instead, so every match is
    rendered as a line. Attribute and text hits and scalar results are always
    lines of stripped, whitespace-collapsed text. An empty result renders as an
    empty payload, so nothing is written at all.
    """
    if isinstance(result, list):
        return _format_node_set(result, extraction, options)
    return _collapse(_scalar_to_string(result))


def _format_node_set(nodes, extraction: TextMode | None, options: OutputOptions) -> str:
    """Render a node-set as text lines, or as XML when nodes are kept as nodes."""
    if extraction is None:
        elements = [node for node in nodes if isinstance(node, etree._Element)]
        if elements:
            return _serialize(elements[0], options.compact)
        return _join_lines((str(node) for node in nodes), options.first)
    return _join_lines(
        (_node_to_text(node, extraction) for node in nodes), options.first
    )


def _node_to_text(node, extraction: TextMode) -> str:
    """Extract an element's text; results that are already text pass through."""
    if isinstance(node, etree._Element):
        return extract_text(node, extraction)
    return str(node)


def _join_lines(values, first: bool) -> str:
    """Put each stripped, collapsed value on its own line, skipping empty ones.

    Dropping the empty values keeps the layout whitespace of an indented
    document from showing up as blank lines among the real text nodes; ``first``
    then keeps only the leading line of what would have been written.
    """
    lines = (line for line in (_collapse(value) for value in values) if line)
    if first:
        return next(lines, "")
    return "\n".join(lines)


def _serialize(element: etree._Element, compact: bool) -> str:
    """Serialize one node, excluding the text that trails its closing tag.

    Compact output leaves the node on a single line; otherwise it is
    pretty-printed with one element per line.
    """
    node = copy.deepcopy(element)
    _drop_layout_whitespace(node)
    xml = etree.tostring(
        node, pretty_print=not compact, with_tail=False, encoding="unicode"
    )
    return xml.rstrip("\n") + "\n"


def _drop_layout_whitespace(element: etree._Element) -> None:
    """Discard the whitespace-only text that pretty-printing re-creates.

    Only whitespace between sibling elements goes; text that carries content
    stays, so mixed content is serialized as it was written.
    """
    for node in element.iter():
        if len(node) and node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None


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
