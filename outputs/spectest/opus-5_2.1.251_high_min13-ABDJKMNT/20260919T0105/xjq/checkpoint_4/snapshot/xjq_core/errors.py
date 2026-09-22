"""Failure types shared by the parsing, query and rendering stages.

Each carries the user-facing message that `xjq` writes to stderr before
exiting with status 1. The wording deliberately contains the keywords the
spec requires: `xml`/`parse` for input problems, `xpath` for query problems,
`css` for selector problems, and `json`/`key`/`invalid` for JSON keys that
cannot name an XML element. The file-input message has no mandated keywords
and names the path instead.
"""


class XjqError(Exception):
    """Base class for conditions that abort the run with exit code 1."""


class XmlInputError(XjqError):
    """Stdin held no document, or one that is not well-formed XML."""

    def __init__(self, detail):
        super().__init__(f"failed to parse xml input: {detail}")


class FileInputError(XjqError):
    """The named `INFILE` could not be read, or is not UTF-8 text."""

    def __init__(self, path, detail):
        super().__init__(f"cannot read file {path!r}: {detail}")


class XPathQueryError(XjqError):
    """The query is not a valid XPath 1.0 expression for this document."""

    def __init__(self, detail):
        super().__init__(f"invalid xpath expression: {detail}")


class CssSelectorError(XjqError):
    """The query is not a valid CSS selector."""

    def __init__(self, detail):
        super().__init__(f"invalid css selector: {detail}")


class MixedTextModeError(XjqError):
    """A comma-separated CSS query asks for two different `::text` modes."""

    def __init__(self):
        super().__init__(
            "invalid css selector: every comma-separated selector must use the "
            "same ::text mode, either direct (sel::text) or descendant (sel ::text)"
        )


class JsonKeyError(XjqError):
    """A JSON object key cannot be used as an XML element name."""

    def __init__(self, key):
        super().__init__(f"invalid json key {key!r}: not a valid xml element name")
