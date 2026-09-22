"""Error type shared by every stage of the merge."""


class MergeError(Exception):
    """A user-facing failure: bad schema, unknown key column, or a fatal cast error."""
