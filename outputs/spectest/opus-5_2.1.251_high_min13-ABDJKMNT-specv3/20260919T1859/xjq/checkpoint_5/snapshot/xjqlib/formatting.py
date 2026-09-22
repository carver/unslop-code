"""Rendering a query result as the payload written to stdout."""

import copy
import math
from dataclasses import dataclass

from lxml import etree

from .jsonexport import export, is_exportable
from .text import TextMode, extract_text, normalize


@dataclass(frozen=True)
class OutputOptions:
    """How the result is written.

    ``first`` keeps one result, ``compact`` drops the added layout of XML and
    JSON output, and ``json_export`` asks for the JSON array instead of a
    serialized node. ``union`` records that the query joined sub-paths with
    ``|``, which changes how ``--text-all`` lays its matches out.
    """

    first: bool = False
    compact: bool = False
    json_export: bool = False
    union: bool = False


def format_result(
    result,
    extraction: TextMode | None = None,
    options: OutputOptions = OutputOptions(),
) -> str:
    """Render a query result for stdout.

    A node-set of elements is rendered as the serialization of its first node,
    as its JSON export, or -- under an extraction mode -- as the text of every
    match. A node-set that holds any string result is text already, so it is
    written as lines whatever the flags ask for. Attribute and text hits and
    scalar results are always lines of stripped, whitespace-collapsed text. An
    empty result renders as an empty payload, so nothing is written at all.
    """
    if isinstance(result, list):
        return _format_node_set(result, extraction, options)
    return normalize(_scalar_to_string(result))


def _format_node_set(nodes, extraction: TextMode | None, options: OutputOptions) -> str:
    """Pick the rendering the node-set's contents and the output flags call for."""
    if any(isinstance(node, str) for node in nodes):
        return _text_results(nodes, options.first)
    if extraction is not None:
        return _extracted_text(nodes, extraction, options)
    if not nodes:
        return ""
    if options.json_export and is_exportable(nodes):
        return export(nodes, options.first, options.compact)
    return _serialize(nodes[0], options.compact)


def _text_results(nodes, first: bool) -> str:
    """Write a node-set that already holds text as one line per result.

    A union whose sub-paths disagree about their result type lands here, and its
    element matches contribute the text of their subtree beside the strings.
    """
    lines = (
        extract_text(node, TextMode.DESCENDANT) if isinstance(node, etree._Element) else node
        for node in nodes
    )
    return _join_lines(lines, first)


def _extracted_text(nodes, extraction: TextMode, options: OutputOptions) -> str:
    """Render matched elements as the text an extraction flag asks for."""
    if options.union and extraction is TextMode.DESCENDANT:
        return _union_text(nodes, options.first)
    return _join_lines((extract_text(node, extraction) for node in nodes), options.first)


def _union_text(nodes, first: bool) -> str:
    """Join the descendant text of every union match into one normalized string.

    ``--first`` narrows the union to the node that matched first, which then
    contributes to the output alone.
    """
    matches = nodes[:1] if first else nodes
    return normalize(
        " ".join(extract_text(node, TextMode.DESCENDANT) for node in matches)
    )


def _join_lines(values, first: bool) -> str:
    """Put each stripped, collapsed value on its own line, skipping empty ones.

    Dropping the empty values keeps the layout whitespace of an indented
    document from showing up as blank lines among the real text nodes; ``first``
    then keeps only the leading line of what would have been written.
    """
    lines = (line for line in (normalize(value) for value in values) if line)
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
