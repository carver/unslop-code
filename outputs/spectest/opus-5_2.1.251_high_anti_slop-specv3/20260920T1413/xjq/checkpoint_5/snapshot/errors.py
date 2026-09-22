"""Failures that xjq reports to the user instead of raising a traceback."""


class XjqError(Exception):
    """Base class for errors whose message is meant for stderr."""


class XmlParseError(XjqError):
    """The input on stdin could not be parsed as an XML/HTML document."""


class XPathError(XjqError):
    """The query is not a usable XPath 1.0 expression."""


class CssError(XjqError):
    """The query is not a CSS selector that xjq can translate."""


class JsonKeyError(XjqError):
    """A JSON object key cannot be used as an XML element name."""


class InputError(XjqError):
    """The document named by INFILE could not be read as UTF-8 text."""
