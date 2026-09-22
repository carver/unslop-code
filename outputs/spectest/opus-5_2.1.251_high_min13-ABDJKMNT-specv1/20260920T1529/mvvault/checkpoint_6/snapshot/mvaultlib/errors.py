"""Error types that map onto the spec's error-handling table."""


class MvaultError(Exception):
    """A user-facing failure: printed to stderr, then exit non-zero."""


class VaultError(MvaultError):
    """A vault is missing, already present, or does not hold a valid catalog."""


class SourceError(MvaultError):
    """The source metadata could not be fetched or did not match the schema."""

    def __init__(self, detail):
        super().__init__(f"Source metadata fetch failure: {detail}")


class AnnotationError(MvaultError):
    """An annotation request refused with one specific HTTP status."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
