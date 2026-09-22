"""Errors that are reported to the user instead of a traceback.

Each class carries the exit code the tool leaves with. The checkpoint numbers
four of them; everything else the user can fix keeps the generic code 1 (see
AMBIGUITIES T34).
"""


class ToolError(Exception):
    """A condition the user can fix: bad schema, unreadable input, bad cast."""

    exit_code = 1


class DetectionError(ToolError):
    """The format of an input could not be determined from name or content."""

    exit_code = 2


class KeyColumnError(ToolError):
    """A ``--key`` column is absent from the resolved schema."""

    exit_code = 3


class SourceFormatError(ToolError):
    """An input violates its dialect: compression mismatch, stray TSV tab, bad JSON."""

    exit_code = 5


class NestedValueError(ToolError):
    """A JSONL or parquet input carries a nested value where only flat ones fit."""

    exit_code = 6
