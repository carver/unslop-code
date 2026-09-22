"""Turning XPath results into the text that the CLI writes to stdout."""

import copy
import math
import re

from lxml import etree

from .nodes import is_element, string_value

INDENT = "  "
_WHITESPACE_RUN = re.compile(r"\s+")


def render(result, first: bool = False, compact: bool = False) -> str:
    """Render an XPath 1.0 result as printable output.

    Node sets whose first member is an element are serialized as XML, showing
    that first node only. Everything else -- attributes, text nodes, strings,
    numbers and booleans -- is rendered as one normalized line per value. An
    empty result renders as the empty string, which the CLI prints as nothing
    at all.

    `first` keeps only the first result of a node set, whatever kind of nodes
    it holds; `compact` drops the pretty-printing from XML serialization.
    """
    if isinstance(result, list):
        nodes = result[:1] if first else result
        if nodes and is_element(nodes[0]):
            return serialize(nodes[0], compact)
        return _render_lines(string_value(node) for node in nodes)
    return _render_lines([_scalar_to_string(result)])


def serialize(node: etree._Element, compact: bool = False) -> str:
    """Serialize `node` as XML, ignoring its surroundings.

    The node is copied so that re-indenting and dropping the trailing text that
    follows it in the source document do not disturb the parsed tree. Compact
    serialization adds no formatting of its own and so leaves whatever
    whitespace the document already had.
    """
    detached = copy.deepcopy(node)
    detached.tail = None
    if compact:
        return etree.tostring(detached, encoding="unicode") + "\n"
    etree.indent(detached, space=INDENT)
    return etree.tostring(detached, pretty_print=True, encoding="unicode")


def _render_lines(values) -> str:
    """Normalize each value and put the non-empty ones on their own line."""
    lines = [normalize(value) for value in values]
    kept = [line for line in lines if line]
    return "".join(f"{line}\n" for line in kept)


def normalize(value: str) -> str:
    """Strip `value` and collapse its internal whitespace runs to single spaces."""
    return _WHITESPACE_RUN.sub(" ", value).strip()


def _scalar_to_string(value) -> str:
    """Apply the XPath 1.0 string() conversion to a number, boolean or string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _number_to_string(value)
    return str(value)


def _number_to_string(value: float) -> str:
    """Format a number the way XPath 1.0 does: 2 rather than 2.0, NaN, Infinity."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value.is_integer():
        return str(int(value))
    return str(value)
