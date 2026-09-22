"""Translating CSS selector queries into XPath.

The translation also recognizes `::text`, a pseudo-element invented by this
tool rather than borrowed from CSS: `p::text` asks for the direct text of every
matched paragraph and `p ::text` for all of its descendant text.
"""

import re

from cssselect import GenericTranslator, SelectorError

from .errors import CssSelectorError
from .text import TextMode

# `::text` may only end a selector. Whether whitespace precedes it -- the
# descendant combinator -- is what tells the two extraction modes apart.
_TEXT_PSEUDO = re.compile(r"(?P<gap>\s*)::text\s*\Z")


def compile_query(query: str) -> tuple[str, TextMode | None]:
    """Translate a CSS selector list into XPath and the text mode it requests.

    Every selector in the list must agree on whether, and how, it extracts
    text, because the result is a single node set rendered one way.
    """
    parts = [_split_text_pseudo(selector) for selector in _split_list(query)]
    modes = {mode for _, mode in parts}
    if len(modes) > 1:
        raise CssSelectorError(
            f"invalid css selector {query!r}: every selector in a list must use "
            "the same ::text mode"
        )
    return _to_xpath(", ".join(selector for selector, _ in parts)), modes.pop()


def _split_list(query: str) -> list[str]:
    """Split a CSS selector list on its top-level commas.

    Commas inside attribute selectors and functional pseudo-classes belong to
    those constructs, so only commas at nesting depth zero separate selectors.
    """
    selectors = [""]
    depth = 0
    for char in query:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            selectors.append("")
        else:
            selectors[-1] += char
    return [selector.strip() for selector in selectors]


def _split_text_pseudo(selector: str) -> tuple[str, TextMode | None]:
    """Strip a trailing `::text` off `selector` and name the mode it asked for."""
    match = _TEXT_PSEUDO.search(selector)
    if match is None:
        return selector, None
    mode = TextMode.DESCENDANT if match["gap"] else TextMode.DIRECT
    return selector[: match.start()].strip(), mode


def _to_xpath(selector: str) -> str:
    """Translate a plain CSS selector list into an equivalent XPath expression.

    `GenericTranslator` matches element names case-sensitively, unlike the HTML
    translator, which keeps CSS mode consistent with the XML parser.
    """
    try:
        return GenericTranslator().css_to_xpath(selector)
    except SelectorError as exc:
        raise CssSelectorError(f"invalid css selector {selector!r}: {exc}") from exc
