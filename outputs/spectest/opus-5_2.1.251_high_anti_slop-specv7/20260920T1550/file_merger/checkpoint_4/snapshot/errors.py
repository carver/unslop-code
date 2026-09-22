"""Errors that are reported to the user instead of raising a traceback.

Each class carries the exit code the tool leaves with, so the caller can map a
failure onto the documented codes without inspecting messages:

===== ==================================================================
Code  Meaning
===== ==================================================================
0     success
1     the output or an input could not be read or written
2     the invocation is unusable, including an undetectable input format
3     a ``--key`` or ``--partition-by`` path is missing or not primitive
4     a cell does not fit its type and ``--on-type-error=fail``
5     an input contradicts its declared dialect, format or compression
6     the schema is unusable, including nested inputs without ``--schema``
===== ==================================================================
"""


class MergeError(Exception):
    """A problem with the invocation, the schema or the data being merged."""

    exit_code = 1


class UsageError(MergeError):
    """The command line asks for something that cannot be carried out."""

    exit_code = 2


class KeyColumnError(MergeError):
    """A field path names nothing the resolved schema can sort or partition on."""

    exit_code = 3


class TypeCastError(MergeError):
    """A cell does not fit its column type and errors are not tolerated."""

    exit_code = 4


class DataError(MergeError):
    """An input does not match the format or compression it was read with."""

    exit_code = 5


class SchemaError(MergeError):
    """The schema cannot be resolved, or an input nests without one."""

    exit_code = 6
