"""Fatal, user-facing errors and the exit code each one carries.

The spec fixes the code for four conditions — undetectable format (2), a key column
missing from the resolved schema (3), an input that violates its own dialect (5) and
a nested JSONL/Parquet structure (6). `MergeError` itself is the catch-all `1`, and
casting failures under ``--on-type-error fail`` take 4 (see AMBIGUITIES T18).
"""


class MergeError(Exception):
    """A fatal error; `merge_files.main` prints it to stderr and exits with `code`."""

    code = 1


class FormatError(MergeError):
    """An input whose format cannot be determined from its name or contents."""

    code = 2


class MissingKeyError(MergeError):
    """A `--key` or `--partition-by` column the resolved schema does not contain."""

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
