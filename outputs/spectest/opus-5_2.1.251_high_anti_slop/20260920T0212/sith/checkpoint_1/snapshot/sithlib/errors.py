"""Errors that abort a run with a message on STDERR."""


class SithError(Exception):
    """A user-facing failure: bad path, undecodable file or out-of-range cursor."""
