"""Translation of CSS selectors, including the custom ``::text``, to XPath."""

from cssselect import GenericTranslator, SelectorError

from xjqlib.scan import split_top_level
from xjqlib.text import TextMode

#: The custom pseudo-element. Attached to a selector (``a::text``) it asks for
#: direct text; preceded by a combinator (``a ::text``) it asks for every
#: descendant text node.
TEXT_PSEUDO = "::text"

# ``GenericTranslator`` matches element names case-sensitively, unlike the HTML
# translator, which matches how the document itself is parsed.
_TRANSLATOR = GenericTranslator()


class CssError(Exception):
    """Raised when a CSS query cannot be turned into a single XPath query."""


def translate(query: str) -> tuple[str, TextMode]:
    """Return the XPath for ``query`` and the text mode its ``::text`` asks for.

    All selectors of a comma-separated list must agree on that mode, since the
    list produces one stream of output.
    """
    parts = [part.strip() for part in split_top_level(query, ",")]
    selectors = [_split_text_pseudo(part) for part in parts]
    modes = {mode for _, mode in selectors}
    if len(modes) > 1:
        raise CssError(
            "all selectors of a comma-separated query must use the same "
            f"{TEXT_PSEUDO} mode"
        )
    xpath = " | ".join(_to_xpath(selector) for selector, _ in selectors)
    return xpath, modes.pop()


def _split_text_pseudo(selector: str) -> tuple[str, TextMode]:
    """Strip a trailing ``::text`` off ``selector`` and report the mode it set.

    Whitespace between the selector and the pseudo-element is the descendant
    combinator, so it selects the text nodes below the match rather than the
    text of the match itself.
    """
    if not selector.endswith(TEXT_PSEUDO):
        return selector, TextMode.NONE
    head = selector[: -len(TEXT_PSEUDO)]
    mode = TextMode.DIRECT if head == head.rstrip() else TextMode.NODES
    return head.rstrip(), mode


def _to_xpath(selector: str) -> str:
    try:
        return _TRANSLATOR.css_to_xpath(selector)
    except SelectorError as exc:
        raise CssError(str(exc)) from exc
