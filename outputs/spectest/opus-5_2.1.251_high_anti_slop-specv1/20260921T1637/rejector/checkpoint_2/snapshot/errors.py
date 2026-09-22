"""Errors reported to the user as a message plus exit code 1, never as a traceback."""


class UserError(Exception):
    """Base class for problems caused by the invocation, config, or input file."""


class ConfigError(UserError):
    """The task configuration is missing, unreadable, or invalid."""


class InputError(UserError):
    """The input file, or one of its rows, cannot be used for this task."""
