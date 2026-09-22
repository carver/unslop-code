"""Shared error type for conditions the tool reports and exits on."""


class MergeError(Exception):
    """A fatal, user-facing error; `merge_files.main` prints it to stderr."""
