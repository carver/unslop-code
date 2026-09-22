"""Failure types shared by the parsing, query and rendering stages.

Each carries the user-facing message that `xjq` writes to stderr before
exiting with status 1. The wording deliberately contains the keywords the
spec requires: `xml`/`parse` for input problems, `xpath` for query problems.
"""


class XjqError(Exception):
    """Base class for conditions that abort the run with exit code 1."""


class XmlInputError(XjqError):
    """Stdin held no document, or one that is not well-formed XML."""

    def __init__(self, detail):
        super().__init__(f"failed to parse xml input: {detail}")


class XPathQueryError(XjqError):
    """The query is not a valid XPath 1.0 expression for this document."""

    def __init__(self, detail):
        super().__init__(f"invalid xpath expression: {detail}")
