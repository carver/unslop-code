"""Translation of CSS selectors, extended with ``::text``, into XPath 1.0."""

import cssselect
from cssselect.parser import CombinedSelector, Element, Selector, Tree
from cssselect.xpath import XPathExpr

from errors import QueryError
from text import TextMode


class _Translator(cssselect.GenericTranslator):
    """A translator that turns down the namespace syntax xjq cannot resolve.

    ``ns|tag`` is valid CSS, but a query names no namespaces, so a prefix is
    reported as an unsupported selector instead of translating into an XPath
    that no document can be evaluated against.
    """

    def xpath_element(self, selector: Element) -> XPathExpr:
        if selector.namespace is not None:
            raise cssselect.ExpressionError(
                f"undeclared namespace prefix {selector.namespace!r}"
            )
        return super().xpath_element(selector)


_TRANSLATOR = _Translator()

# CSS selectors match anywhere in the document, XPath steps do not.
_PREFIX = "descendant-or-self::"

# The step appended to a translated selector for each ``::text`` mode.
_TEXT_STEP = {None: "", TextMode.DIRECT: "/text()", TextMode.DESCENDANT: "//text()"}


def translate(selector: str) -> str:
    """Return the XPath 1.0 expression equivalent to the CSS ``selector``.

    A ``|`` is read as CSS — the namespace separator — rather than as the XPath
    union operator, and so is rejected along with any other unsupported syntax.

    ``selector::text`` selects the direct text nodes of the matched elements and
    ``selector ::text`` all of their descendant text nodes. Comma-separated
    selectors are joined into a single expression, provided they agree on which
    of those two modes — or neither — they use.

    Raises:
        QueryError: if ``selector`` is not a supported CSS selector, or its
            comma-separated parts disagree about the ``::text`` mode.
    """
    parts = _parse(selector)
    modes = {_text_mode(part) for part in parts}
    if len(modes) > 1:
        raise QueryError(
            f"css selector {selector!r} mixes ::text modes; every "
            "comma-separated selector must use the same one"
        )
    mode = modes.pop()
    return " | ".join(_translate_part(part, mode) for part in parts)


def _parse(selector: str) -> list[Selector]:
    """Parse ``selector`` into one parsed selector per comma-separated part."""
    try:
        return cssselect.parse(selector)
    except cssselect.SelectorError as exc:
        raise QueryError(f"invalid css selector {selector!r}: {exc}") from exc


def _text_mode(part: Selector) -> TextMode | None:
    """Return the ``::text`` mode ``part`` asks for, or None if it asks for none.

    A trailing ``::text`` reads the matched elements' own text; one written as a
    descendant — ``a ::text``, parsed as the universal selector below ``a`` —
    reads every text node underneath them.
    """
    if part.pseudo_element is None:
        return None
    if part.pseudo_element != "text":
        raise QueryError(f"unsupported pseudo-element ::{part.pseudo_element}")
    if _is_bare_descendant(part.parsed_tree):
        return TextMode.DESCENDANT
    return TextMode.DIRECT


def _is_bare_descendant(tree: Tree) -> bool:
    """Whether ``tree`` ends in a descendant combinator and a bare ``*``."""
    return (
        isinstance(tree, CombinedSelector)
        and tree.combinator == " "
        and isinstance(tree.subselector, Element)
        and tree.subselector.element is None
    )


def _translate_part(part: Selector, mode: TextMode | None) -> str:
    """Translate one comma-separated selector, reading text as ``mode`` says."""
    tree = part.parsed_tree
    if mode is TextMode.DESCENDANT:
        tree = tree.selector
    try:
        path = _TRANSLATOR.xpath(tree)
    except cssselect.SelectorError as exc:
        raise QueryError(f"unsupported css selector {part!r}: {exc}") from exc
    return f"{_PREFIX}{path}{_TEXT_STEP[mode]}"
