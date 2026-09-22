"""Error type for problems that should be reported to the user, not traced.

Each error carries the exit code the program ends with, so the caller only
has to print the message and hand the code back to the shell.
"""

EXIT_GENERAL = 1
# The command line does not describe a runnable merge, which includes an
# input whose format could not be named.
EXIT_USAGE = 2
EXIT_SCHEMA = 3
EXIT_SOURCE = 5
EXIT_NESTED = 6


class MergeError(Exception):
    """A condition the user can fix: bad schema, unknown key, failed cast."""

    def __init__(self, message: str, exit_code: int = EXIT_GENERAL) -> None:
        super().__init__(message)
        self.exit_code = exit_code
