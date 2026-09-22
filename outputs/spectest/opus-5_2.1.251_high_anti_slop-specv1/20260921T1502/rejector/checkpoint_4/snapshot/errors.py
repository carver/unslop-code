"""Error type shared by the modules that validate user supplied files."""


class UsageError(Exception):
    """A configuration or input problem: reported on stderr with exit code 1."""
