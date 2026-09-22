"""The error type reported to the user, carrying the exit code the spec assigns.

The spec names codes 2, 3, 5 and 6 explicitly; 1 and 4 fill the remaining classes
as recorded in ambiguity T21.
"""

EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_SCHEMA = 3
EXIT_TYPE = 4
EXIT_INPUT = 5
EXIT_NESTED = 6


class MergeError(Exception):
    """A condition the spec asks us to report on stderr and exit non-zero for."""

    def __init__(self, message: str, code: int = EXIT_ERROR):
        super().__init__(message)
        self.code = code
