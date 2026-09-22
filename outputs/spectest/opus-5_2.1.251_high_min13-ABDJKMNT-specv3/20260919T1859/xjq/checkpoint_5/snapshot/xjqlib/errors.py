"""The error type shared by the parsing and evaluation stages."""


class XjqError(Exception):
    """A failure to report on stderr, after which the command exits with 1."""
