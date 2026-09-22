"""Fatal, user-facing errors and the exit code each one carries.

The spec fixes the code for five conditions — undetectable format and alias cycles
(2), a key path that does not name a primitive (3), a cast failure under
``--on-type-error fail`` (4), an input that violates its own dialect (5) and nested
input without a schema (6). `MergeError` itself is the catch-all `1`, which is also
what an unusable schema document exits with (see AMBIGUITIES T18, T51).

`merge_files.main` prints every one of them as ``ERR <code> <message>`` (T45).
"""


class MergeError(Exception):
    """A fatal error; `merge_files.main` prints it to stderr and exits with `code`."""

    code = 1


class SchemaError(MergeError):
    """A `--schema` or `--type-alias-file` document that cannot be used."""


class FormatError(MergeError):
    """An input whose format cannot be determined from its name or contents."""

    code = 2


class AliasCycleError(SchemaError):
    """A type alias that resolves, transitively, back to itself."""

    code = 2


class MissingKeyError(MergeError):
    """A `--key` or `--partition-by` path that names nothing in the resolved schema."""

    code = 3


class KeyPathError(MergeError):
    """A `--key` or `--partition-by` path whose value is not a primitive."""

    code = 3


class CastFailure(MergeError):
    """A cell that cannot be cast, under ``--on-type-error fail``."""

    code = 4


class InputError(MergeError):
    """An input that contradicts its declared dialect or compression."""

    code = 5


class NestedDataError(MergeError):
    """A JSONL or Parquet field holding an array, object, list or map."""

    code = 6
