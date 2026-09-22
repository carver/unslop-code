"""Evaluation of XPath 1.0 expressions against a parsed document."""

from lxml import etree

from errors import QueryError

# An XPath 1.0 result: a node/string list, or a boolean, number or string.
Result = list | bool | float | str


def evaluate(root: etree._Element, expression: str) -> Result:
    """Evaluate ``expression`` against the document rooted at ``root``.

    Raises:
        QueryError: if ``expression`` is not a valid XPath 1.0 expression.
    """
    try:
        return root.xpath(expression)
    except etree.XPathError as exc:
        raise QueryError(f"invalid xpath expression {expression!r}: {exc}") from exc
