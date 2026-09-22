"""Evaluation of CSS selectors, extended with a ``::text`` pseudo-element.

``selector::text`` selects the direct text nodes of the matched elements and
``selector ::text`` -- the same selector followed by a descendant step -- all
of their descendant text nodes. A query is CSS throughout, so ``|`` keeps its
CSS meaning of a namespace separator instead of joining two queries.
"""

import cssselect
from cssselect.parser import CombinedSelector, Element
from lxml import etree

from errors import CssError
from text_extract import TextMode

_TEXT_PSEUDO_ELEMENT = "text"
_DESCENDANT_COMBINATOR = " "
_ROOT_PREFIX = "descendant-or-self::"
_TRANSLATOR = cssselect.GenericTranslator()


def evaluate_css(document, query: str):
    """Evaluate the CSS ``query`` against ``document``.

    Returns the matched elements, or their text nodes when the query uses the
    ``::text`` pseudo-element.

    Raises:
        CssError: if the query is not a CSS selector the document can be
            matched against.
    """
    try:
        return document.xpath(_to_xpath(query))
    except etree.XPathError as exc:
        raise CssError(f"css error: {exc}") from exc


def _to_xpath(query: str) -> str:
    """Translate ``query``, including any ``::text``, into an XPath expression."""
    try:
        selectors = cssselect.parse(query)
        modes = {_text_mode(selector) for selector in selectors}
        if len(modes) > 1:
            raise CssError(
                "css error: every selector of a comma-separated query must use "
                "the same ::text mode"
            )
        mode = modes.pop()
        return " | ".join(_selector_xpath(selector, mode) for selector in selectors)
    except cssselect.SelectorError as exc:
        raise CssError(f"css error: {exc}") from exc


def _text_mode(selector):
    """Return the ``TextMode`` a parsed selector asks for, or ``None``."""
    pseudo_element = selector.pseudo_element
    if pseudo_element is None:
        return None
    if pseudo_element != _TEXT_PSEUDO_ELEMENT:
        raise CssError(f"css error: unsupported pseudo-element ::{pseudo_element}")
    if _ends_in_descendant_step(selector.parsed_tree):
        return TextMode.DESCENDANT
    return TextMode.DIRECT


def _ends_in_descendant_step(tree) -> bool:
    """Report whether ``tree`` ends in a bare descendant step, as in ``div ::text``."""
    return (
        isinstance(tree, CombinedSelector)
        and tree.combinator == _DESCENDANT_COMBINATOR
        and isinstance(tree.subselector, Element)
        and tree.subselector.element is None
    )


def _selector_xpath(selector, mode) -> str:
    """Return the XPath for one parsed selector of the query."""
    tree = selector.parsed_tree
    if mode is TextMode.DESCENDANT:
        return f"{_element_xpath(tree.selector)}//text()"
    if mode is TextMode.DIRECT:
        return f"{_element_xpath(tree)}/text()"
    return _element_xpath(tree)


def _element_xpath(tree) -> str:
    """Translate a parsed selector tree into a path rooted at the document."""
    return _ROOT_PREFIX + str(_TRANSLATOR.xpath(tree))
