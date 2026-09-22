"""Extraction of the text carried by the elements a query matched."""

from lxml import etree

DIRECT = "direct"
ALL = "all"

_TEXT_PATH = {DIRECT: "text()", ALL: "descendant-or-self::text()"}


def extract(result, mode):
    """Return `result` with every matched element replaced by its text nodes.

    `mode` is `DIRECT` for the text nodes that are direct children of an
    element, `ALL` for every text node below it, or None to return `result`
    unchanged. Values that are not elements -- the strings a query such as
    `//p/text()` or `p::text` already yields -- are passed through, which is
    what makes the text modes no-op modifiers for those queries.
    """
    if mode is None or not isinstance(result, list):
        return result
    return [value for node in result for value in _texts(node, mode)]


def _texts(node, mode):
    """Return the text values `node` contributes to the result."""
    if etree.iselement(node):
        return node.xpath(_TEXT_PATH[mode])
    return [node]
