"""Error type shared by the xjq modules."""


class XjqError(Exception):
    """A user-facing failure: its message is printed to stderr before exiting."""
