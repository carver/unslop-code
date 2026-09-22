"""Error types that map to the CLI's exit code 1."""


class RejectorError(Exception):
    """Base for configuration and input errors reported on stderr."""


class ConfigError(RejectorError):
    """The task configuration is missing, unparsable, or invalid."""


class InputError(RejectorError):
    """The JSONL input is unreadable, malformed, or missing a needed field."""
