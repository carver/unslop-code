"""Errors that the CLI reports to the user instead of a traceback."""


class XjqError(Exception):
    """Base class for failures that map to exit code 1 with a stderr message."""


class XmlParseError(XjqError):
    """The input on stdin is not a well-formed, non-empty XML document."""


class XPathQueryError(XjqError):
    """The query is not a usable XPath 1.0 expression."""


class CssSelectorError(XjqError):
    """The query is not a usable CSS selector list."""


class JsonKeyError(XjqError):
    """A JSON key cannot be used as an XML element name."""


class InputReadError(XjqError):
    """The file named by INFILE cannot be read as UTF-8 text."""
