"""Errors reported to the user as CLI failures."""


class MVaultError(Exception):
    """Base class for failures that end a command with a stderr message."""


class InvalidVaultError(MVaultError):
    """Raised when a vault directory is missing or its catalog is unusable."""


class VaultWriteError(MVaultError):
    """Raised when a vault file cannot be backed up or written."""


class SourceError(MVaultError):
    """Raised when source metadata cannot be fetched or does not match the schema."""
