"""Error type shared by the ingestion pipeline and the HTTP layer."""


class ApiError(Exception):
    """A failure that maps directly onto a JSON error response."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status
