"""Extraction of the text carried by the elements a query matched."""

import re

from lxml import etree

DIRECT = "direct"
ALL = "all"

_TEXT_PATH = {DIRECT: "text()", ALL: "descendant-or-self::text()"}

_WHITESPACE_RUN = re.compile(r"\s+")


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


def joined(nodes, mode):
    """Return the `mode` text of every node in `nodes` as one normalized string.

    This is the single-value counterpart of `extract`: the text nodes it would
    yield are run together, separated by the whitespace that already stands
    between the words of a document, instead of being kept apart as a list.
    """
    return normalize(" ".join(extract(nodes, mode)))


def normalize(text):
    """Strip `text` and collapse every internal run of whitespace to one space."""
    return _WHITESPACE_RUN.sub(" ", text).strip()


def _texts(node, mode):
    """Return the text values `node` contributes to the result."""
    if etree.iselement(node):
        return node.xpath(_TEXT_PATH[mode])
    return [node]
