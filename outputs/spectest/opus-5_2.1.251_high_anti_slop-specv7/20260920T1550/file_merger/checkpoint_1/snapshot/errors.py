"""Errors that are reported to the user instead of raising a traceback."""


class MergeError(Exception):
    """A problem with the invocation, the schema or the data being merged."""
