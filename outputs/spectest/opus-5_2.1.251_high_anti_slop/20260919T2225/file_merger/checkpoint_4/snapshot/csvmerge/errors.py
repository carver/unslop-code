"""Errors shared by every stage of the merge.

Each carries the ``ERR`` number its message is reported under and the process
exit code it produces. The two agree everywhere except a rejected cast, which
is reported as ``ERR 4`` but keeps the exit code 1 it has always had.
"""


class MergeError(Exception):
    """A user-facing failure. Subclasses refine the error number and exit code."""

    code = 1
    exit_code = 1


class FormatDetectionError(MergeError):
    """An input whose format cannot be determined from its name or contents."""

    code = 2
    exit_code = 2


class AliasError(MergeError):
    """A type alias file that cannot be used, most often because it is cyclic."""

    code = 2
    exit_code = 2


class SchemaError(MergeError):
    """An unusable schema, or a key or partition path the schema cannot resolve."""

    code = 3
    exit_code = 3


class CastError(MergeError):
    """A value rejected by ``--on-type-error fail``."""

    code = 4
    exit_code = 1


class MalformedInputError(MergeError):
    """An input that does not match its declared dialect or compression."""

    code = 5
    exit_code = 5


class NestedDataError(MergeError):
    """A nested input value with no ``--schema`` declaring how to read it."""

    code = 6
    exit_code = 6
