"""The single error type that the CLI reports to the user."""


class MvaultError(Exception):
    """A failure that must be printed to stderr and exit non-zero.

    Every operational failure -- an existing vault directory, an unusable
    vault, an unreachable or malformed source -- is raised as this type so the
    CLI layer never has to distinguish between them.
    """
