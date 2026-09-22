"""Errors that are reported to the user instead of a traceback."""


class ToolError(Exception):
    """A condition the user can fix: bad schema, unknown key column, bad cast."""
