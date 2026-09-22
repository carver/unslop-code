"""Failure type reported by the CLI as a stderr message and a non-zero exit."""


class MvaultError(Exception):
    """A user-facing failure; its message is printed verbatim to stderr."""
