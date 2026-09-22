"""Translation of CSS selectors into the XPath expressions xjq evaluates.

CSS is extended with a custom `::text` pseudo-element: `p::text` selects the
text nodes that are direct children of the matched elements, while its
descendant form `p ::text` selects every text node below them.
"""

import cssselect
from cssselect.parser import CombinedSelector, Element, Selector

import textnodes

_TRANSLATOR = cssselect.GenericTranslator()

_TEXT_STEP = {textnodes.DIRECT: "/text()", textnodes.ALL: "//text()"}


class CssQueryError(Exception):
    """The query is not a usable CSS selector."""


def translate(query):
    """Translate the CSS selector `query` into `(xpath, text_mode)`.

    `text_mode` is the `textnodes` mode asked for by a `::text`
    pseudo-element, or None when the query selects elements. Comma-separated
    selectors become an XPath union and must agree on that mode.
    """
    try:
        translated = [_translate_one(sel) for sel in cssselect.parse(query)]
    except cssselect.SelectorError as exc:
        raise CssQueryError(exc) from exc
    modes = {mode for _, mode in translated}
    if len(modes) > 1:
        raise CssQueryError("every selector must use the same ::text mode")
    return " | ".join(xpath for xpath, _ in translated), modes.pop()


def _translate_one(selector):
    """Translate one parsed selector of a query into `(xpath, text_mode)`."""
    if selector.pseudo_element is None:
        return _to_xpath(selector.parsed_tree), None
    if str(selector.pseudo_element) != "text":
        raise CssQueryError(f"unknown pseudo-element ::{selector.pseudo_element}")
    tree, mode = _split_text_target(selector.parsed_tree)
    return _to_xpath(tree) + _TEXT_STEP[mode], mode


def _split_text_target(tree):
    """Return the elements a `::text` selector applies to and its text mode.

    `p ::text` parses as `p` combined with a universal selector; that trailing
    universal selector is what tells the descendant form from plain `p::text`.
    """
    if isinstance(tree, CombinedSelector) and tree.combinator == " ":
        subselector = tree.subselector
        if isinstance(subselector, Element) and subselector.element is None:
            return tree.selector, textnodes.ALL
    return tree, textnodes.DIRECT


def _to_xpath(tree):
    """Translate a parsed selector tree, pseudo-element aside, into XPath."""
    return _TRANSLATOR.selector_to_xpath(Selector(tree))
