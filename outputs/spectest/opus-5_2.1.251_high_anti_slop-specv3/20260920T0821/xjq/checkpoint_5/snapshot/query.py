"""Evaluation of XPath 1.0 expressions against a parsed document."""

import re

from lxml import etree

from errors import QueryError

# An XPath 1.0 result: a node/string list, or a boolean, number or string.
Result = list | bool | float | str

_STRING_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")


def evaluate(root: etree._Element, expression: str) -> Result:
    """Evaluate ``expression`` against the document rooted at ``root``.

    A union of paths joined with ``|`` evaluates to the nodes all of them match,
    in document order and without duplicates.

    Raises:
        QueryError: if ``expression`` is not a valid XPath 1.0 expression.
    """
    try:
        return root.xpath(expression)
    except etree.XPathError as exc:
        raise QueryError(f"invalid xpath expression {expression!r}: {exc}") from exc


def is_union(expression: str) -> bool:
    """Whether ``expression`` joins several paths with the ``|`` operator.

    A ``|`` inside a string literal is part of a value being compared, not a
    union of paths.
    """
    return "|" in _STRING_LITERAL.sub("", expression)
