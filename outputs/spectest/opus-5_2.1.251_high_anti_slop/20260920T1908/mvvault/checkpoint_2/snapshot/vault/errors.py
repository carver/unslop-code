"""Failures mvault reports on stderr instead of raising a traceback."""


class VaultError(Exception):
    """Raised when a vault directory or its catalog is missing or not usable."""


class SourceError(Exception):
    """Raised when source metadata cannot be fetched or cannot be trusted."""
