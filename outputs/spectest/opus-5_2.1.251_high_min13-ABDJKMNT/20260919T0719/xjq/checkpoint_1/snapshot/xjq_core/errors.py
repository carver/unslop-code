"""Errors that the CLI reports to the user instead of a traceback."""


class XjqError(Exception):
    """Base class for failures that map to exit code 1 with a stderr message."""


class XmlParseError(XjqError):
    """The input on stdin is not a well-formed, non-empty XML document."""


class XPathQueryError(XjqError):
    """The query is not a usable XPath 1.0 expression."""
