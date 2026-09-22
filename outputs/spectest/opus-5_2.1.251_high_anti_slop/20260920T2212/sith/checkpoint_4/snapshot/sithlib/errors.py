"""Errors that translate into a non-zero exit status."""


class SithError(Exception):
    """A user facing failure: bad path, undecodable file or out of range cursor."""
