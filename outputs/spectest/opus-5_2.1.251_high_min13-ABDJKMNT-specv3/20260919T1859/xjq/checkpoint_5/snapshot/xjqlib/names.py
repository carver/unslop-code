"""Deciding whether a string may be used as an XML element name."""

import re

# The XML 1.0 ``NameStartChar`` and ``NameChar`` ranges, without the colon:
# a colon would introduce a namespace prefix that a converted document has no
# way to declare, and that the tree builder rejects anyway.
_START_CHARS = (
    "A-Z_a-zÀ-ÖØ-öø-˿Ͱ-ͽͿ-῿"
    "‌-‍⁰-↏Ⰰ-⿯、-퟿豈-﷏"
    "ﷰ-�\U00010000-\U000effff"
)
_OTHER_CHARS = _START_CHARS + "0-9\\-.·̀-ͯ‿-⁀"
_NAME = re.compile(f"[{_START_CHARS}][{_OTHER_CHARS}]*\\Z")


def is_xml_name(name: str) -> bool:
    """Tell whether ``name`` is a usable XML element name."""
    return _NAME.match(name) is not None
