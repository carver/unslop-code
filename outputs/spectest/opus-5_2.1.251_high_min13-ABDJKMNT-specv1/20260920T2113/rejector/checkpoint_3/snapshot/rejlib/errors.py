"""Error types shared across the library."""


class ConfigError(Exception):
    """Invalid configuration or input; the CLI maps this to exit code 1."""
