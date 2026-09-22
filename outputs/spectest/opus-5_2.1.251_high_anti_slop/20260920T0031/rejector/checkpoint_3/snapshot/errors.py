"""Error type for problems the user can fix in their config or input file."""


class RejectorError(Exception):
    """Invalid task configuration or malformed input data (CLI exit code 1)."""
