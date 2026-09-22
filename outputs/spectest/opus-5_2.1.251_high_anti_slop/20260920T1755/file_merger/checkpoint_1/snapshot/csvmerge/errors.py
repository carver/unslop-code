"""Error type for problems that should be reported to the user, not traced."""


class MergeError(Exception):
    """A condition the user can fix: bad schema, unknown key, failed cast."""
