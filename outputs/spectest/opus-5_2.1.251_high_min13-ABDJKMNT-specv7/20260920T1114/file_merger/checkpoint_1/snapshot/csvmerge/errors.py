"""The single error type reported to the user."""


class MergeError(Exception):
    """A condition the spec asks us to report on stderr and exit non-zero for."""
