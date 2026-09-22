"""The failures the tool reports, each carrying the exit code it exits with.

Every error the user can trigger derives from :class:`MergeError`, so the CLI
catches one type and reads ``exit_code`` off it instead of mapping messages to
statuses.
"""

from __future__ import annotations


class MergeError(RuntimeError):
    """A user-facing failure that aborts the run."""

    exit_code = 1


class SchemaError(MergeError):
    """A schema file is missing, malformed or names an unknown type."""


class UsageError(MergeError):
    """The command line does not describe a runnable merge."""

    exit_code = 2


class KeyColumnError(MergeError):
    """A ``--key`` path is absent from the schema or is not a primitive."""

    exit_code = 3


class TypeCastError(MergeError):
    """A cell does not fit its column's type and ``--on-type-error`` says fail."""

    exit_code = 4


class SourceFormatError(MergeError):
    """An input does not match the dialect or compression it was read with."""

    exit_code = 5


class NestedDataError(MergeError):
    """An input carries nested values but no ``--schema`` declares their shape."""

    exit_code = 6
