"""Translating CSS selectors, including the custom ``::text``, into XPath."""

from cssselect import GenericTranslator, parse
from cssselect.parser import CombinedSelector, Element, Selector, SelectorError

from .errors import XjqError
from .text import TextMode

_TRANSLATOR = GenericTranslator()
_TEXT = "text"


def translate_selector(selector: str) -> str:
    """Translate a CSS selector into the equivalent XPath expression.

    ``selector::text`` selects the direct child text nodes of the matched
    elements, and ``selector ::text`` every text node below them. The parts of
    a comma-separated selector must agree on one of those modes, or on
    selecting elements; mixing them raises :class:`XjqError`.
    """
    try:
        parts = parse(selector)
    except SelectorError as error:
        raise XjqError(f"invalid css selector {selector!r}: {error}") from error

    modes = {_text_mode(part, selector) for part in parts}
    if len(modes) > 1:
        raise XjqError(
            f"invalid css selector {selector!r}: "
            "direct and descendant ::text cannot be mixed in one query"
        )
    mode = modes.pop()
    return " | ".join(_part_to_xpath(part, mode) for part in parts)


def _text_mode(part: Selector, selector: str) -> TextMode | None:
    """Classify one comma-separated part by the ``::text`` mode it asks for."""
    if part.pseudo_element is None:
        return None
    if part.pseudo_element != _TEXT:
        raise XjqError(
            f"invalid css selector {selector!r}: "
            f"unsupported pseudo-element ::{part.pseudo_element}"
        )
    return TextMode.DESCENDANT if _has_descendant_step(part) else TextMode.DIRECT


def _has_descendant_step(part: Selector) -> bool:
    """Tell ``selector ::text`` from ``selector::text``.

    The whitespace of the former parses as a descendant combinator whose right
    side is the universal selector CSS implies before a bare pseudo-element.
    """
    tree = part.parsed_tree
    return (
        isinstance(tree, CombinedSelector)
        and tree.combinator == " "
        and isinstance(tree.subselector, Element)
        and tree.subselector.element is None
    )


def _part_to_xpath(part: Selector, mode: TextMode | None) -> str:
    """Render one part as XPath, with the text step its mode calls for."""
    if mode is TextMode.DESCENDANT:
        # The matched elements are the ones on the left of the combinator; their
        # own text nodes count as descendant text, so the universal selector on
        # the right is replaced rather than translated.
        elements = _TRANSLATOR.selector_to_xpath(Selector(part.parsed_tree.selector))
        return f"{elements}/descendant-or-self::*/text()"
    elements = _TRANSLATOR.selector_to_xpath(part)
    return f"{elements}/text()" if mode is TextMode.DIRECT else elements
