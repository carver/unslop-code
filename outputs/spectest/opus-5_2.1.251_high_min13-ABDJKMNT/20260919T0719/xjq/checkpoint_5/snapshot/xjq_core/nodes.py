"""Questions about the members of an evaluated node set.

lxml returns a node set as a plain list holding elements, comments and string
subclasses standing for text nodes and attribute values, so telling those kinds
apart is what decides both how a result is rendered and what can be extracted
from it.
"""

from lxml import etree


def is_element(node) -> bool:
    """Report whether `node` is an XML element.

    Comments and processing instructions subclass the element type in lxml but
    carry a callable `tag` instead of a name, which is how they are excluded.
    """
    return isinstance(node, etree._Element) and isinstance(node.tag, str)


def is_element_set(result) -> bool:
    """Report whether `result` is a non-empty node set made only of elements."""
    return isinstance(result, list) and bool(result) and all(map(is_element, result))


def string_value(node) -> str:
    """Return the XPath 1.0 string value of one node-set member.

    Text nodes and attribute values already are that string; an element or a
    comment is asked for the text it contains.
    """
    return node.xpath("string()") if isinstance(node, etree._Element) else str(node)
