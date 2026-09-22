"""Formatting of XPath results into the text written to stdout."""

import copy

from lxml import etree

from text_extract import TextMode, element_text, normalize_text

_INDENT = "  "


def render(result, first: bool = False, compact: bool = False) -> str:
    """Return the stdout text for an XPath ``result``, without a trailing newline.

    A node set of elements is rendered as the XML of its first element; a node
    set that holds anything else -- strings, or the mix of strings and elements
    a union query can produce -- is rendered as one whitespace-normalized line
    per result, or as a single line when ``first`` is set. ``compact`` drops the
    pretty-printing of XML output, leaving the document's own layout.
    """
    if not isinstance(result, list):
        return _render_scalar(result)
    if first:
        result = result[:1]
    if not result:
        return ""
    if is_element_list(result):
        return _serialize(result[0], compact)
    return "\n".join(normalize_text(_text_value(item)) for item in result)


def is_element_list(result) -> bool:
    """Report whether ``result`` is a node set that holds elements only."""
    return (
        isinstance(result, list)
        and bool(result)
        and all(etree.iselement(item) for item in result)
    )


def _text_value(item) -> str:
    """Return the text an item of a node set contributes to a line of output.

    An element stands for all of the text it contains, which is what XPath
    takes the string value of a node to be.
    """
    if etree.iselement(item):
        return element_text(item, TextMode.DESCENDANT)
    return item


def _render_scalar(value) -> str:
    """Render the boolean, number or string produced by an XPath function."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return number_text(value)
    return normalize_text(value)


def number_text(value: float) -> str:
    """Return the shortest string that denotes the number ``value``."""
    return str(int(value)) if value.is_integer() else repr(value)


def _serialize(node, compact: bool) -> str:
    """Return the XML of ``node`` and its descendants, pretty-printed unless ``compact``."""
    if compact:
        return etree.tostring(node, with_tail=False, encoding="unicode").strip()
    indented = copy.deepcopy(node)
    etree.indent(indented, space=_INDENT)
    xml = etree.tostring(indented, pretty_print=True, with_tail=False, encoding="unicode")
    return xml.strip()
