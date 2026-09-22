"""Translation of CSS selectors, with a ``::text`` extension, into XPath."""

from cssselect import GenericTranslator, SelectorError
from cssselect.parser import CombinedSelector, Element, Selector, Tree, parse
from cssselect.xpath import ExpressionError

from .errors import XjqError
from .text import TextMode

_TRANSLATOR = GenericTranslator()


def css_to_xpath(selector: str) -> str:
    """Translate the CSS ``selector`` into the equivalent XPath expression.

    ``sel::text`` selects the direct text nodes of the matched elements while
    ``sel ::text`` selects their descendant text nodes. Comma-separated
    selectors become an XPath union and have to agree on their ``::text`` mode.

    Raises:
        XjqError: the selector is not valid CSS or mixes ``::text`` modes.
    """
    try:
        parts = [_split_text_mode(parsed) for parsed in parse(selector)]
        if len({mode for _, mode in parts}) > 1:
            raise XjqError(
                f"error: invalid css selector {selector!r}: comma-separated "
                "selectors must all use the same ::text mode"
            )
        return " | ".join(_part_to_xpath(tree, mode) for tree, mode in parts)
    except SelectorError as exc:
        raise XjqError(f"error: invalid css selector {selector!r}: {exc}") from exc


def _split_text_mode(parsed: Selector) -> tuple[Tree, TextMode]:
    """Split one parsed selector into its element tree and its text mode.

    The parser turns the descendant form ``sel ::text`` into ``sel`` combined
    with a universal selector, which is what tells the two ``::text`` forms
    apart.
    """
    if parsed.pseudo_element is None:
        return parsed.parsed_tree, TextMode.NONE
    if parsed.pseudo_element != "text":
        raise ExpressionError(f"the pseudo-element ::{parsed.pseudo_element} is unknown")
    if _is_descendant_of_universal(parsed.parsed_tree):
        return parsed.parsed_tree.selector, TextMode.DESCENDANT
    return parsed.parsed_tree, TextMode.DIRECT


def _is_descendant_of_universal(tree: Tree) -> bool:
    """Tell whether ``tree`` ends in a descendant step onto a universal selector."""
    return (
        isinstance(tree, CombinedSelector)
        and tree.combinator == " "
        and isinstance(tree.subselector, Element)
        and tree.subselector.element is None
    )


def _part_to_xpath(tree: Tree, mode: TextMode) -> str:
    """Translate one selector tree, appending the text step ``mode`` asks for."""
    xpath = _TRANSLATOR.selector_to_xpath(Selector(tree, None))
    if mode is TextMode.NONE:
        return xpath
    return f"{xpath}/{mode.value}"
