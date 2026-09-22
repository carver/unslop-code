"""Exceptions that map to the CLI's failure modes."""


class XjqError(Exception):
    """Base class for errors that should be reported to the user, not traced."""


class DocumentError(XjqError):
    """The input could not be parsed as an XML document."""


class QueryError(XjqError):
    """The query is not a usable XPath expression."""
