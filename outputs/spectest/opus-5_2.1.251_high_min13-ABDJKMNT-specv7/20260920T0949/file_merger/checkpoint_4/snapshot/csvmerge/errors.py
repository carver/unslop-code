"""Errors that are reported to the user instead of a traceback.

Each class carries the exit code the tool leaves with. The checkpoints number
five of them; everything else the user can fix keeps the generic code 1 (see
AMBIGUITIES T34).
"""


class ToolError(Exception):
    """A condition the user can fix: bad schema, unreadable input, bad cast."""

    exit_code = 1


class UsageError(ToolError):
    """The command line, or a file it names, is not usable as given."""

    exit_code = 2


class DetectionError(UsageError):
    """The format of an input could not be determined from name or content."""


class KeyColumnError(ToolError):
    """A ``--key`` or ``--partition-by`` path names no primitive value."""

    exit_code = 3


class CastFailure(ToolError):
    """A value did not fit its declared type under ``--on-type-error fail``."""

    exit_code = 4


class SourceFormatError(ToolError):
    """An input violates its dialect: compression mismatch, stray TSV tab, bad JSON."""

    exit_code = 5


class NestedValueError(ToolError):
    """A JSONL or parquet input carries a nested value where only flat ones fit."""

    exit_code = 6
