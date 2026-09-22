"""Error type reported by the CLI as a stderr message plus a non-zero exit."""


class MvaultError(Exception):
    """A condition the user is expected to see, never a stack trace."""
