"""The failure codes the tool exits with, and the exception that carries them."""

#: A command line that does not describe a runnable merge, including an input
#: whose format cannot be determined.
EXIT_USAGE = 2
#: The output schema could not be resolved: unusable `--schema`, unknown type
#: name, or a `--key` column that the resolved schema does not contain.
EXIT_SCHEMA = 3
#: A cell would not cast to its column type under `--on-type-error fail`.
EXIT_CAST = 4
#: Source bytes do not match the format they were declared to be in.
EXIT_SOURCE = 5
#: A nested value in a format the spec restricts to flat records.
EXIT_NESTED = 6


class MergeError(Exception):
    """An operational failure, reported on stderr with its own exit code."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code
