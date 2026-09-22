"""Errors shared by every stage of the merge, each carrying its exit code."""


class MergeError(Exception):
    """A user-facing failure. Subclasses refine the process exit code."""

    exit_code = 1


class FormatDetectionError(MergeError):
    """An input whose format cannot be determined from its name or contents."""

    exit_code = 2


class SchemaError(MergeError):
    """An unusable schema file, or a key column missing from the resolved schema."""

    exit_code = 3


class MalformedInputError(MergeError):
    """An input that does not match its declared dialect or compression."""

    exit_code = 5


class NestedDataError(MergeError):
    """A JSON Lines or Parquet input carrying nested values; only flat records are supported."""

    exit_code = 6
